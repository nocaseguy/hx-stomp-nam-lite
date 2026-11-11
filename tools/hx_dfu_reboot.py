#!/usr/bin/env python3
"""
hx_dfu_reboot.py - ask a running Line 6 HX Stomp to reboot into its USB DFU
loader (re-enumerates as NXP 1fc9:000c), the way "Line 6 Updater" does in its
"Putting the device into DFU mode" / "Rebooting into NX bootloader" step.
Works on the unit (2026-10-25: stock 3.80 application run from RAM by
tools/hxf_ram.py; in DFU about two seconds later). Quit HX Edit first: it
holds interface 0.

Wire protocol (as Line 6 Updater speaks it, checked against the unit):

USB:   config 0, interface 0 (class 0xFF), alt 0, one bulk OUT + one bulk IN
       endpoint. One message per OUT transfer, zero-padded to a multiple of 4.
       IN transfers are read in mtu-sized chunks and may hold several messages,
       each padded to 4 bytes. mtu = wMaxPacketSize of the bulk IN endpoint.

Transport header (8 bytes, 2 x u32 LE):
       w0 = type<<28 | ver<<26 | len      (ver=2; len = bytes after this header)
       w1 = src | dst<<16                 (host 0x1001 -> device 0x03EF)
       type 2 = stream SYN (an extra u32 follows: mtu<<16), type 1 = other.

Stream header (8 bytes, 2 x u32 LE) after the transport header (and the extra
word on SYN):
       w0 = flags<<24 | seq<<8            flags: 01 SYN, 02 FIN, 04 DATA,
                                                 08 window update, 10 heartbeat,
                                                 20 (on SYN) heartbeats wanted
       w1 = receive-window edge = rx buffer size (0x1000) + bytes consumed
       seq: per-direction 8-bit counter, SYN carries 1, every later packet +1;
       a receiver drops the stream on any gap.

Session on device port 0xEF (librarian), stock app service #3:
  host -> {u16 0, u16 3, u32 1, 03}               select service 3 (no reply)
  host -> {u16 1, u16 0, u32 2, 00 00}            "version handshake"
  dev  -> {u16 0, u16 3, u32 2, 00 00}
  then raw 4-byte UUE commands {AA 00 00 cmd}:
     cmd 1 QueryUpdateProtocolInfo -> 4 bytes  (01 04 04 04)
     cmd 3 QueryDeviceInfo         -> 36 bytes
     cmd 2 EnterUpdateMode         -> 4 bytes DeviceResult (0), then ~1 s later
                                      the app writes "BootIntoDfu!" at
                                      0x1001FF00 and resets.

Use --dry-run to print every transfer without touching USB.
"""

import argparse
import struct
import sys
import time

VID_LINE6 = 0x0E41
PID_HX_STOMP = 0x4246          # "P33"
PID_HX_STOMP_XL = 0x4253       # "P36"; Line 6's updater in RAM also comes up as 4253, on either unit
VID_DFU, PID_DFU = 0x1FC9, 0x000C

LOCAL_ADDR = 0x1001            # ConnectionParameters[0]: 10 00 01 02 | 03 ed ef f0
REMOTE_ADDR = 0x03EF           # librarian port; host masks dst with 0x3ff on the wire
RX_BUF = 0x1000                # Updater stream rx buffer -> initial window edge
HB_INTERVAL = 1.0              # Updater: heartbeat interval 1000 ms, timeout 4000 ms

F_SYN, F_FIN, F_DATA, F_WIN, F_HB, F_HBREQ = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20


class ProtocolError(Exception):
    pass


def hexs(b):
    return ' '.join('%02x' % x for x in b)


def transport_hdr(ttype, length, src, dst, ver=2):
    w0 = ((ttype & 0xF) << 28) | ((ver & 3) << 26) | (length & 0xFFFF)
    w1 = (src & 0xFFFF) | ((dst & 0xFFFF) << 16)
    return struct.pack('<II', w0, w1)


def stream_hdr(flags, seq, window):
    return struct.pack('<II', ((flags & 0xFF) << 24) | ((seq & 0xFF) << 8), window & 0xFFFFFFFF)


def pad4(b):
    return b + b'\0' * (-len(b) % 4)


def parse_in_transfer(buf):
    """Split one IN transfer into messages: list of dicts."""
    out, off = [], 0
    while off + 8 <= len(buf):
        w0, w1 = struct.unpack_from('<II', buf, off)
        ttype, ver, ln = w0 >> 28, (w0 >> 26) & 3, w0 & 0xFFFF
        if off + 8 + ln > len(buf):
            raise ProtocolError('truncated message at %d: %s' % (off, hexs(buf[off:])))
        body = buf[off + 8: off + 8 + ln]
        msg = dict(type=ttype, ver=ver, src=w1 & 0xFFFF, dst=w1 >> 16, raw=buf[off:off + 8 + ln])
        p = 0
        if ttype == 2:
            if len(body) < 4:
                raise ProtocolError('SYN without mtu word')
            msg['mtu'] = struct.unpack_from('<I', body, 0)[0] >> 16
            p = 4
        if len(body) - p < 8:
            msg['flags'] = None          # not a stream packet
        else:
            s0, s1 = struct.unpack_from('<II', body, p)
            msg.update(flags=s0 >> 24, seq=(s0 >> 8) & 0xFF, window=s1, data=body[p + 8:])
        out.append(msg)
        off += (8 + ln + 3) & ~3
    return out


# --------------------------------------------------------------------------- USB back ends

class UsbLink:
    def __init__(self, pid, timeout_ms, verbose):
        try:
            import usb.core
            import usb.util
        except ImportError:
            sys.exit('error: pyusb is not installed (pip install pyusb; libusb must be present)')
        self.usb = usb
        self.verbose = verbose
        self.timeout_ms = timeout_ms
        if pid is None:                 # the one HX Stomp or HX Stomp XL there
            devs = [d for d in usb.core.find(find_all=True, idVendor=VID_LINE6)
                    if d.idProduct in (PID_HX_STOMP, PID_HX_STOMP_XL)]
            if len(devs) > 1:
                sys.exit('error: several Line 6 devices (%s); pick one with --pid'
                         % ', '.join('%04x' % d.idProduct for d in devs))
            pid = devs[0].idProduct if devs else PID_HX_STOMP
        dev = usb.core.find(idVendor=VID_LINE6, idProduct=pid)
        if dev is None:
            if usb.core.find(idVendor=VID_DFU, idProduct=PID_DFU) is not None:
                sys.exit('error: a 1fc9:000c DFU device is already present; the unit is already in its DFU loader')
            sys.exit('error: no %04x:%04x device found (is the unit on and running its normal firmware?)'
                     % (VID_LINE6, pid))
        self.dev = dev
        try:
            cfg = dev.get_active_configuration()
        except usb.core.USBError as e:
            sys.exit('error: cannot read the active configuration: %s' % e)
        intf = cfg[(0, 0)]
        if intf.bInterfaceClass == 1:
            sys.exit('error: interface 0 is an audio interface; not the HX message interface')
        eps = list(intf)
        bulk = [e for e in eps if usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK]
        if len(eps) != 2 or len(bulk) != 2:
            sys.exit('error: interface 0 does not have exactly two bulk endpoints')
        self.ep_in = next(e for e in bulk if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        self.ep_out = next(e for e in bulk if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self.mtu = self.ep_in.wMaxPacketSize
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(dev, 0)
        except usb.core.USBError as e:
            sys.exit('error: cannot claim interface 0 (%s). Quit HX Edit, Line 6 Updater and anything else '
                     'talking to the unit, then retry.' % e)
        print('found %04x:%04x, interface 0: OUT 0x%02x, IN 0x%02x, mtu %d'
              % (VID_LINE6, pid, self.ep_out.bEndpointAddress, self.ep_in.bEndpointAddress, self.mtu))

    def write(self, data, what):
        print('OUT ep 0x%02x %3d bytes  %-26s %s' % (self.ep_out.bEndpointAddress, len(data), what, hexs(data)))
        try:
            n = self.dev.write(self.ep_out, data, timeout=5000)      # Updater: 5000 ms
        except self.usb.core.USBError as e:
            raise ProtocolError('bulk OUT failed: %s' % e)
        if n != len(data):
            raise ProtocolError('short bulk OUT: %d of %d' % (n, len(data)))

    def read(self, timeout_ms=100):                                   # Updater: 100 ms IN requests
        try:
            b = bytes(self.dev.read(self.ep_in, self.mtu, timeout=timeout_ms))
        except self.usb.core.USBTimeoutError:
            return b''
        except self.usb.core.USBError as e:
            if getattr(e, 'errno', None) in (60, 110) or 'timed out' in str(e).lower():
                return b''
            raise ProtocolError('bulk IN failed: %s' % e)
        if b:
            print('IN  ep 0x%02x %3d bytes  %-26s %s' % (self.ep_in.bEndpointAddress, len(b), '', hexs(b)))
        return b

    def purge(self, seconds=1.0):
        """Line 6 Updater discards inbound data for ~1 s before use; so do we."""
        end = time.monotonic() + seconds
        n = 0
        while time.monotonic() < end:
            try:
                n += len(self.dev.read(self.ep_in, self.mtu, timeout=100))
            except self.usb.core.USBError:
                pass
        if n:
            print('purged %d stale inbound bytes' % n)

    def close(self):
        try:
            self.usb.util.release_interface(self.dev, 0)
        except self.usb.core.USBError:
            pass
        self.usb.util.dispose_resources(self.dev)


# Device replies for --dry-run, as the stock app sends them.
SIM_PROTOCOL_INFO = bytes.fromhex('01040404')
SIM_DEV_INFO = bytes.fromhex('00000000030000000100000000000000020000000000000003000000'
                             '0100000000000000')                                # 36 bytes


class DryLink:
    """Prints OUT transfers and plays the stock app's side so the host state machine runs."""

    def __init__(self, mtu):
        self.mtu = mtu
        self.queue = []
        self.dev_seq = 0
        self.dev_window = 0x200        # device stream rx buffer
        self.rx = b''                  # bytes the device's stream has received
        self.stage = 0
        print('[dry-run] no USB access; IN data below is simulated from the stock app\'s code')
        print('[dry-run] assuming OUT ep 0x01, IN ep 0x81, mtu %d' % mtu)

    def _dev_send(self, flags, data=b'', syn=False):
        self.dev_seq = (self.dev_seq + 1) & 0xFF
        sh = stream_hdr(flags, self.dev_seq, self.dev_window)
        if syn:
            body = struct.pack('<I', 0x200 << 16) + sh + data
            msg = transport_hdr(2, len(body), REMOTE_ADDR, LOCAL_ADDR) + body
        else:
            body = sh + data
            msg = transport_hdr(1, len(body), REMOTE_ADDR, LOCAL_ADDR) + body
        self.queue.append(pad4(msg))

    def write(self, data, what):
        print('OUT ep 0x01 %3d bytes  %-26s %s' % (len(data), what, hexs(data)))
        m = parse_in_transfer(data)[0]
        if m['flags'] & F_SYN:
            self.dev_seq = 0
            self._dev_send(F_SYN, syn=True)
            return
        if not m['flags'] & F_DATA:
            return
        self.rx += m['data']
        while True:
            if self.stage == 0 and len(self.rx) >= 9:          # service select, no reply
                self.rx, self.stage = self.rx[9:], 1
            elif self.stage == 1 and len(self.rx) >= 10:       # version msg -> hello
                payload = self.rx[8:10]
                self.rx, self.stage = self.rx[10:], 2
                self._dev_send(F_DATA, struct.pack('<HHI', 0, 3, 2) + payload)
            elif self.stage == 2 and len(self.rx) >= 4:
                cmd, self.rx = self.rx[3], self.rx[4:]
                if cmd == 1:
                    self._dev_send(F_DATA, SIM_PROTOCOL_INFO)
                elif cmd == 3:
                    self._dev_send(F_DATA, SIM_DEV_INFO)
                elif cmd == 2:
                    self._dev_send(F_DATA, b'\0\0\0\0')
            else:
                break

    def read(self, timeout_ms=100):
        if not self.queue:
            return b''
        b = self.queue.pop(0)
        print('IN  ep 0x81 %3d bytes  %-26s %s' % (len(b), '(simulated)', hexs(b)))
        return b

    def purge(self, seconds=1.0):
        print('[dry-run] would drain the IN endpoint for %.1f s (Updater "purging")' % seconds)

    def close(self):
        pass


# --------------------------------------------------------------------------- stream

class Stream:
    def __init__(self, link, local, remote, heartbeat=True):
        self.link = link
        self.local, self.remote = local, remote
        self.tx_seq = 1                  # MsgPort_Stream_Connect sets it to 1
        self.rx_seq = None
        self.consumed = 0
        self.sent = 0
        self.peer_window = 0
        self.peer_mtu = 0
        self.rxbuf = b''
        self.heartbeat = heartbeat
        self.last_tx = time.monotonic()

    def _send(self, flags, data=b'', what=''):
        sh = stream_hdr(flags, self.tx_seq, RX_BUF + self.consumed)
        if flags & F_SYN:
            body = struct.pack('<I', (self.link.mtu & 0xFFFF) << 16) + sh + data
            msg = transport_hdr(2, len(body), self.local, self.remote & 0x3FF) + body
        else:
            body = sh + data
            msg = transport_hdr(1, len(body), self.local, self.remote & 0x3FF) + body
        self.link.write(pad4(msg), what)
        self.tx_seq = (self.tx_seq + 1) & 0xFF
        self.sent += len(data)
        self.last_tx = time.monotonic()

    def _handle(self, m):
        if m['flags'] is None:
            print('    (ignoring non-stream message type %d)' % m['type'])
            return
        if (m['src'] & 0xFF) != (self.remote & 0xFF) or m['dst'] != self.local:
            print('    (ignoring message %04x -> %04x, not our stream)' % (m['src'], m['dst']))
            return
        f = m['flags']
        if f & F_SYN:
            if self.rx_seq is not None:
                raise ProtocolError('unexpected SYN from device after connect')
            self.rx_seq = m['seq']
            self.peer_mtu = m.get('mtu', 0)
            self.peer_window = m['window']
            print('    device SYN: seq %d, mtu %d, window edge 0x%x' % (m['seq'], self.peer_mtu, m['window']))
            return
        if self.rx_seq is None:
            raise ProtocolError('device sent a non-SYN packet before connecting')
        if ((m['seq'] - self.rx_seq) & 0xFF) != 1:
            raise ProtocolError('device sequence gap: got %d after %d' % (m['seq'], self.rx_seq))
        self.rx_seq = m['seq']
        if f & (F_DATA | F_WIN):
            self.peer_window = m['window']
            if f & F_DATA and m['data']:
                self.rxbuf += m['data']
        if f & F_FIN:
            raise ProtocolError('device closed the stream (FIN); it rejected the request')

    def poll(self, timeout_ms=100):
        b = self.link.read(timeout_ms)
        for m in parse_in_transfer(b) if b else []:
            self._handle(m)
        if self.heartbeat and self.rx_seq is not None and time.monotonic() - self.last_tx >= HB_INTERVAL:
            self._send(F_HB, what='heartbeat')
        return bool(b)

    def connect(self, timeout):
        self._send(F_SYN | (F_HBREQ if self.heartbeat else 0), what='SYN -> 0x%04x' % self.remote)
        end = time.monotonic() + timeout
        while self.rx_seq is None:
            if time.monotonic() > end:
                raise ProtocolError('no SYN reply from the device within %.1f s' % timeout)
            self.poll()

    def write(self, data, what, timeout):
        end = time.monotonic() + timeout
        while self.sent + len(data) > self.peer_window:
            if time.monotonic() > end:
                raise ProtocolError('device window closed for %.1f s' % timeout)
            self.poll()
        if self.peer_mtu and len(data) > self.peer_mtu - 16:
            raise ProtocolError('payload larger than device mtu')
        self._send(F_DATA, data, what)

    def read(self, n, timeout, what):
        end = time.monotonic() + timeout
        while len(self.rxbuf) < n:
            if time.monotonic() > end:
                raise ProtocolError('timed out after %.1f s waiting for %s (%d of %d bytes)'
                                    % (timeout, what, len(self.rxbuf), n))
            self.poll()
        out, self.rxbuf = self.rxbuf[:n], self.rxbuf[n:]
        self.consumed += n
        return out

    def sleep(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.poll(int(max(1, min(100, (end - time.monotonic()) * 1000))))

    def window_update(self):
        # The Updater's Read() schedules a flags=08 packet after consuming data.
        self._send(F_WIN, what='window update')


# --------------------------------------------------------------------------- main

def run(link, args):
    st = Stream(link, args.local_addr, REMOTE_ADDR, heartbeat=not args.no_heartbeat)
    link.purge(0.2 if args.dry_run else 1.0)

    print('-- connect stream to port 0x%04x' % REMOTE_ADDR)
    st.connect(args.timeout)

    print('-- select service 3 on port 0xEF (mode 1)')
    st.write(struct.pack('<HHIB', 0, 3, 1, 3), 'select service 3', args.timeout)
    st.sleep(0.0 if args.dry_run else 0.425)      # Updater: 400 ms + 25 ms

    print('-- version handshake')
    st.write(struct.pack('<HHI', 1, 0, 2) + b'\0\0', 'version msg', args.timeout)
    hdr = st.read(8, args.timeout, 'hello header')
    a, svc, ln = struct.unpack('<HHI', hdr)
    if ln != 2:
        raise ProtocolError('unexpected hello length %d (header %s); not the stock update service' % (ln, hexs(hdr)))
    st.read(ln, args.timeout, 'hello payload')
    print('    hello ok: service %d' % svc)
    st.window_update()

    if not args.minimal:
        print('-- QueryUpdateProtocolInfo (cmd 1)')
        st.write(b'\xAA\x00\x00\x01', 'cmd 1', args.timeout)
        pi = st.read(4, args.timeout, 'ProtocolInfo')
        print('    ProtocolInfo: %s' % hexs(pi))
        if pi[0] >= 2 or not all(1 <= x <= 4 for x in pi[1:]):
            raise ProtocolError('ProtocolInfo rejected by the Updater\'s checks: %s' % hexs(pi))
        st.window_update()

        print('-- QueryDeviceInfo (cmd 3)')
        st.write(b'\xAA\x00\x00\x03', 'cmd 3', args.timeout)
        di = st.read(36, args.timeout, 'DevInfo')
        print('    DevInfo: %s' % hexs(di))
        st.window_update()

    print('-- EnterUpdateMode (cmd 2) -> device writes "BootIntoDfu!" and resets ~1 s later')
    st.write(b'\xAA\x00\x00\x02', 'cmd 2', args.timeout)
    res = st.read(4, args.timeout, 'DeviceResult')
    code = struct.unpack('<i', res)[0]
    print('    DeviceResult: %d' % code)
    if code < 0:
        raise ProtocolError('device refused EnterUpdateMode (result %d)' % code)


def wait_for_dfu(seconds):
    import usb.core
    print('waiting up to %d s for %04x:%04x ...' % (seconds, VID_DFU, PID_DFU))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if usb.core.find(idVendor=VID_DFU, idProduct=PID_DFU) is not None:
            print('DFU loader present: %04x:%04x' % (VID_DFU, PID_DFU))
            return True
        time.sleep(0.25)
    print('warning: %04x:%04x did not appear within %d s' % (VID_DFU, PID_DFU, seconds))
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--pid', type=lambda s: int(s, 0), default=None,
                    help='USB product id of the running unit (default: the one HX Stomp 0x4246 or HX Stomp XL 0x4253)')
    ap.add_argument('--dry-run', action='store_true', help='print every transfer, touch no USB device')
    ap.add_argument('--mtu', type=int, default=512, help='bulk IN wMaxPacketSize to assume in --dry-run')
    ap.add_argument('--timeout', type=float, default=3.0, help='seconds to wait for each reply (default 3)')
    ap.add_argument('--wait', type=int, default=15, help='seconds to wait for 1fc9:000c afterwards (0 = skip)')
    ap.add_argument('--minimal', action='store_true',
                    help='skip cmd 1/cmd 3 and send only EnterUpdateMode (the app does not require them)')
    ap.add_argument('--no-heartbeat', action='store_true',
                    help='SYN flags 0x01 instead of the Updater\'s 0x21 and no heartbeats')
    ap.add_argument('--local-addr', type=lambda s: int(s, 0), default=LOCAL_ADDR,
                    help='host stream address (Updater uses 0x1001 for its first device)')
    ap.add_argument('--verbose', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()

    link = DryLink(args.mtu) if args.dry_run else UsbLink(args.pid, int(args.timeout * 1000), args.verbose)
    try:
        run(link, args)
    except ProtocolError as e:
        link.close()
        sys.exit('error: %s' % e)
    except KeyboardInterrupt:
        link.close()
        sys.exit('interrupted')
    link.close()
    if args.dry_run:
        print('[dry-run] done; a real run would now wait for %04x:%04x' % (VID_DFU, PID_DFU))
        return
    print('reboot requested')
    if args.wait > 0 and not wait_for_dfu(args.wait):
        sys.exit(1)


if __name__ == '__main__':
    main()
