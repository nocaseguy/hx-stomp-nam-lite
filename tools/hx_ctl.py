#!/usr/bin/env python3
"""
hx_ctl.py - control a running HX Stomp (stock 3.80 app) over USB the way HX Edit
does: select presets, read the edit buffer, write the edit buffer (whole preset
or one block's model), list presets. Importable (class HxCtl) and a CLI.

Protocol (as seen from the host and checked on the unit):
  USB/transport/stream layer: tools/hx_dfu_reboot.py (UsbLink, Stream), reused.
  HX Edit opens three streams (modes 2, 3, 5):
     host 0x1000 <-> dev 0x03ED  mode 2 -> service 6  "editor"    (HelixEditorService)
     host 0x1001 <-> dev 0x03EF  mode 3 -> service 2  "librarian" (HelixLibrarianService)
     host 0x1002 <-> dev 0x03F0  mode 5 -> service 4  "notify"    (HelixNotifyService)
  On each stream: select service {u16 1, u16 svc, u32 1, u8 svc}; device replies
  {u16 0, u16 0, u32 1, u8 svc}. Then messages {u16 1, u16 svc, u32 len} + MessagePack
  request {0x66: seq, 0x64: cmd, 0x65: params}; reply {u16 0, u16 svc, u32 len} +
  {0x66: seq, 0x67: status (0 ok, 255 error), 0x68: result or {0x6f: errcode}}.
  Editor commands used here (service 6):
     0x14 load preset {0x6b: setlist, 0x6c: preset}   (switches preset; no flash write)
     0x15 set edit buffer {0x6e: <l6-helix preset blob>} (edit buffer only; no save)
     0x16 get edit buffer -> <l6-helix preset blob>
     0x17 get current preset -> {0x6b: setlist, 0x6c: preset, 0x6d: name, 0x75: modified?, ...}
     0x2b move a block {0x4b: from, 0x4c: to} (grid positions = preset[0][22] indices:
          10 * path + slot + 1 on the Stomp)
  Librarian (service 2): 0x01 preset list {0x6b: setlist}.
  Nothing here saves to the unit's storage (HX Edit's "save" is a separate command that
  this tool does not send).

Preset blob (l6-helix): fixstr "l6-helix\\0", str16 48-byte offset table (12 x u32 LE),
then one MessagePack map {7: meta, 0: blocks, 1, 3, 4, 2, 5, 6, 10}. The table holds the
buffer offsets of: the map, key 0, 1, 3, 4, 2, 5, 6, 7, 10, end, end.
Blocks: preset[0][22] is a list of 20 entries {19: type, 20: body}:
  index 0 input A, 1..8 path A slots 0..7, 9 output A, 10 split, 11..18 path B slots 0..7,
  19 join. type 8 = empty slot (body None), 6 = processing block with
  body {24: {23: amp+cab?, 25: preset_id, 26: cab id or -1}, 9: kind, 10: enabled,
        11: {2: n, 3: n, 4: [values]}, 12: {2: 0, 3: 0, 4: []}}.

Examples:
  hx_ctl.py status
  hx_ctl.py select 3                    # preset 3 (0-based) of the current setlist, via USB
  hx_ctl.py select 3 --midi             # same with a USB-MIDI Program Change
  hx_ctl.py presets
  hx_ctl.py get-preset -o cur.json
  hx_ctl.py set-model --slot 0 --model-id 572 --clear-after
  hx_ctl.py load-preset cur.json
  hx_ctl.py --dry-run set-model --slot 0 --model-id 572 --clear-after
  hx_ctl.py move --from 0:2 --to 0:0    # the block at path A slot 2 to slot 0, as HX Edit drags it
"""

import argparse
import contextlib
import io
import json
import copy
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import msgpack                                    # noqa: E402
import hx_dfu_reboot as hxu                       # noqa: E402  (UsbLink, Stream; not modified)

EDITOR = dict(local=0x1000, remote=0x03ED, svc=6)
LIBRARIAN = dict(local=0x1001, remote=0x03EF, svc=2)
NOTIFY = dict(local=0x1002, remote=0x03F0, svc=4)

K_SEQ, K_CMD, K_PARAMS, K_STATUS, K_RESULT, K_ERR = 0x66, 0x64, 0x65, 0x67, 0x68, 0x6F
K_SETLIST, K_PRESET, K_NAME, K_PBLOB = 0x6B, 0x6C, 0x6D, 0x6E

CMD_LOAD_PRESET, CMD_SET_EDITBUF, CMD_GET_EDITBUF, CMD_GET_CURRENT = 0x14, 0x15, 0x16, 0x17
CMD_MOVE_BLOCK = 0x2B
K_MOVE_FROM, K_MOVE_TO = 0x4B, 0x4C
CMD_LIB_PRESET_LIST = 0x01

PATH_A_SLOTS = list(range(1, 9))       # preset[0][22] indices
PATH_B_SLOTS = list(range(11, 19))
EMPTY_TYPE = 8
BLOCK_TYPE = 6
SECTION_ORDER = [0, 1, 3, 4, 2, 5, 6, 7, 10]   # offset-table order after the map offset

# Block "kind" (body key 9) for models whose kind can't be found in the current preset.
# 572 (Kit Probe, amp category 12) and 147 (NAM) are amps without cab: 17 (seen on the unit).
KNOWN_KIND = {572: 17, 147: 17}
# Kinds whose parameter list carries one more value than its key-3 count says (delay and
# reverb 8, 9, 15, 16: every such block in the 122 factory presets; the rest list as many as
# they count). A block written with key 3 = len(values) for these is dropped by the unit,
# and a few such presets in a row hang it.
SHORT_COUNT_KINDS = {8, 9, 15, 16}
# Parameter values to use when neither the preset nor the factory presets have the model:
# 572 "Kit Probe" has one parameter; the unit's edit buffer held [0.5] on 2026-10-28.
KNOWN_PARAMS = {572: [0.5]}


class HxError(Exception):
    pass


PENDING = object()      # request accepted (status 1); completion is reported on the notify port


# --------------------------------------------------------------------------- preset codec

def _unpack(b):
    return msgpack.unpackb(b, raw=False, strict_map_key=False, unicode_errors='surrogateescape')


def _pack(o):
    return msgpack.packb(o, use_bin_type=True, use_single_float=True,
                         unicode_errors='surrogateescape')


def decode_preset(blob):
    """l6-helix blob -> (magic str, sections dict). Raises HxError if it isn't one."""
    up = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
    up.feed(blob)
    try:
        magic, table, sec = up.unpack(), up.unpack(), up.unpack()
    except Exception as e:
        raise HxError('not an l6-helix preset blob: %s' % e)
    if not (isinstance(magic, str) and magic.startswith('l6-helix') and isinstance(sec, dict)):
        raise HxError('not an l6-helix preset blob')
    if up.tell() != len(blob):
        raise HxError('trailing bytes after the preset map (%d of %d used)' % (up.tell(), len(blob)))
    return magic, sec


def raw_sections(blob):
    """{section key: (decoded value, exact value bytes)} of a unit-made blob."""
    up = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
    up.feed(blob)
    up.unpack(), up.unpack()
    p = up.tell()
    n = blob[p] & 0x0F
    if blob[p] & 0xF0 != 0x80:
        raise HxError('preset map is not a fixmap')
    p += 1
    up = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
    up.feed(blob[p:])
    out = {}
    for _ in range(n):
        k = up.unpack()
        a = up.tell()
        v = up.unpack()
        out[k] = (v, blob[p + a:p + up.tell()])
    return out


def encode_preset(magic, sec, like=None):
    """sections dict -> l6-helix blob with a recomputed offset table.
    like: an original blob; sections whose value is unchanged are copied byte for byte
    (the unit writes some ints wider than MessagePack needs, e.g. d1 00 00 in section 2)."""
    raw = raw_sections(like) if like else {}
    head = _pack(magic)
    table_len = 48
    table_hdr = b'\xda' + struct.pack('>H', table_len)       # str16, as the unit writes it
    map_off = len(head) + len(table_hdr) + table_len
    n = len(sec)
    if n > 15:
        raise HxError('too many sections')
    body = bytes([0x80 | n])
    offs = {}
    for k, v in sec.items():
        offs[k] = map_off + len(body)
        vb = raw[k][1] if k in raw and raw[k][0] == v else _pack(v)
        body += _pack(k) + vb
    end = map_off + len(body)
    words = [map_off] + [offs.get(k, end) for k in SECTION_ORDER] + [end, end]
    table = struct.pack('<12I', *words)
    return head + table_hdr + table + body


def blocks(sec):
    return sec[0][22]


def slot_index(path, pos):
    if not 0 <= pos <= 7:
        raise HxError('slot position must be 0..7')
    return (PATH_A_SLOTS if path == 0 else PATH_B_SLOTS)[pos]


def summarize(sec):
    out = []
    bl = blocks(sec)
    for path, idxs in ((0, PATH_A_SLOTS), (1, PATH_B_SLOTS)):
        for pos, i in enumerate(idxs):
            e = bl[i]
            if e.get(19) == EMPTY_TYPE or e.get(20) is None:
                continue
            body = e[20]
            m = body.get(24, {}) if isinstance(body, dict) else {}
            vals = body.get(11, {}).get(4) if isinstance(body.get(11), dict) else None
            out.append(dict(path=path, slot=pos, type=e.get(19), model_id=m.get(25), cab_id=m.get(26),
                            kind=body.get(9), enabled=body.get(10), params=vals))
    return out


# The stock factory presets (Entry 12 of a stock .hxf) give each model's block kind and default
# knob values. Read from your own stock firmware file: $HX_STOMP_HXF, or the Stomp's 3.80.0 .hxf
# in the repository root.
FACTORY_PRESETS = os.environ.get('HX_STOMP_HXF') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'HX_Stomp_v3.80.0_0x103966115.hxf')


_FACTORY_BYTES = {}


def _factory_bytes(path):
    """Entry 12 (word-swapped) of a stock .hxf or .l6ia, or the bytes of an extracted entry; cached."""
    if path not in _FACTORY_BYTES:
        _FACTORY_BYTES[path] = _read_factory(path)
    return _FACTORY_BYTES[path]


def _read_factory(path):
    if path.endswith(('.hxf', '.l6ia')):
        import patch_amp
        l6ia_bytes, _ = patch_amp.load_l6ia_from_any(path)
        return patch_amp.get_entry_swapped(l6ia_bytes, 12)
    return open(path, 'rb').read()


def _find_in_blocks(bl, model_id):
    for e in bl:
        b = e.get(20) if isinstance(e, dict) else None
        if isinstance(b, dict) and isinstance(b.get(24), dict) and b[24].get(25) == model_id \
                and b[24].get(26, -1) == -1:
            return b.get(9), list(b.get(11, {}).get(4, []))
    return None, None


def _factory_block_lists(factory=FACTORY_PRESETS):
    """Each stock factory preset's block list (Entry 12 of the stock .hxf), cached."""
    if factory in _FACTORY_CACHE:
        return _FACTORY_CACHE[factory]
    out = []
    if factory and os.path.exists(factory):
        up = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
        up.feed(_factory_bytes(factory)[0x40:])
        try:
            for o in up:
                if isinstance(o, dict) and isinstance(o.get(22), list):
                    out.append(o[22])
                elif isinstance(o, (bytes, str)) and len(o) > 200 and not (isinstance(o, str) and o.startswith('l6-helix')):
                    try:
                        raw = o.encode('utf-8', 'surrogateescape') if isinstance(o, str) else o
                        out.append(blocks(decode_preset(raw)[1]))
                    except Exception:
                        pass
        except Exception:
            pass
    _FACTORY_CACHE[factory] = out
    return out


_FACTORY_CACHE = {}
# Cab blocks: a single cab (browser category 14 sub 0, e.g. 795) is an ordinary kind-31 block
# (7 knobs, the same for every cab); a dual cab (kind 32, 25 and 26 the two cabs), an amp + cab
# (kind 33, legacy 18) and a legacy cab (kind 16) carry a cab half: 24[23] set and a second
# values list under key 12 (find_cab_template).
SINGLE_CAB_KIND = 31


def kind_params(kind, factory=FACTORY_PRESETS):
    """The values of the first factory block of this kind (its knob layout), or None."""
    for bl in _factory_block_lists(factory):
        for e in bl:
            b = e.get(20) if isinstance(e, dict) else None
            if isinstance(b, dict) and b.get(9) == kind and isinstance(b.get(11), dict):
                return list(b[11][4])
    return None


def find_cab_template(sec, model_id, cab_id=None, factory=FACTORY_PRESETS):
    """A block body with a cab half (24[23], 26 a cab, values under key 12) for model_id (and cab_id):
    from the preset, then the factory presets; None when there is no such block to copy."""
    lists = [blocks(sec)] + _factory_block_lists(factory)
    def cabs():
        for bl in lists:
            for e in bl:
                b = e.get(20) if isinstance(e, dict) else None
                if isinstance(b, dict) and isinstance(b.get(24), dict) and b[24].get(23) and isinstance(b.get(12), dict):
                    yield b
    for b in cabs():
        if b[24].get(25) == model_id and (cab_id is None or b[24].get(26) == cab_id):
            return copy.deepcopy(b)
    return None


def find_kind_and_params(sec, model_id, factory=FACTORY_PRESETS):
    """(kind, values) of a block with this model: first in the given preset, then in the
    stock factory presets (Entry 12 of the stock .hxf), else (None, None)."""
    k, p = _find_in_blocks(blocks(sec), model_id)
    if k is not None or not factory or not os.path.exists(factory):
        return k, p
    d = _factory_bytes(factory)
    up = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
    up.feed(d[0x40:])
    try:
        for o in up:
            cands = []
            if isinstance(o, dict) and isinstance(o.get(22), list):
                cands.append(o[22])
            elif isinstance(o, str) and o.startswith('l6-helix'):
                continue
            elif isinstance(o, (bytes, str)) and len(o) > 200:
                try:
                    raw = o.encode('utf-8', 'surrogateescape') if isinstance(o, str) else o
                    _, ps = decode_preset(raw)
                    cands.append(blocks(ps))
                except Exception:
                    pass
            for bl in cands:
                k, p = _find_in_blocks(bl, model_id)
                if k is not None:
                    return k, p
    except Exception:
        pass
    return None, None


def _used(bl, i):
    return bl[i].get(19) != EMPTY_TYPE and bl[i].get(20) is not None


def last_used_pos(sec, path=0):
    """The last position used on either path: the Stomp's paths share one row of 8 positions
    (a position holds one block, on path A or B; the unit shows only one of two blocks at the
    same position), so 'end' is after both."""
    bl = blocks(sec)
    used = [pos for pos in range(8) if _used(bl, PATH_A_SLOTS[pos]) or _used(bl, PATH_B_SLOTS[pos])]
    return used[-1] if used else -1


def check_position_free(sec, path, pos):
    """HxError when the other path has a block at pos (the Stomp's paths share the positions)."""
    other = PATH_B_SLOTS if path == 0 else PATH_A_SLOTS
    if _used(blocks(sec), other[pos]):
        raise HxError('position %d is used on path %d: the HX Stomp\'s paths share 8 positions, '
                      'one block each (use PATH:end or a free position)' % (pos, 1 - path))


def set_model(sec, path, pos, model_id, params=None, kind=None, enabled=True, clear_after=False,
              clear_path_b=False, cab_id=None):
    """Edit sections in place: put model_id into (path, pos). cab_id: a block with a cab half
    (a dual cab's second cab, an amp's cab); cab blocks are copied from a block of the same
    model (find_cab_template), params replacing its first values list."""
    bl = blocks(sec)
    i = slot_index(path, pos)
    k0, p0 = find_kind_and_params(sec, model_id)
    tpl = find_cab_template(sec, model_id, cab_id) if cab_id is not None or (k0 is None and kind is None) else None
    if tpl is not None:
        if params is not None:
            short = tpl[11][2] - tpl[11][3]
            tpl[11] = {2: len(params), 3: len(params) - short, 4: list(params)}
        tpl[10] = bool(enabled)
        bl[i] = {19: BLOCK_TYPE, 20: tpl}
        _clear(bl, path, pos, clear_after, clear_path_b)
        check_position_free(sec, path, pos)
        return sec
    if kind is None:
        kind = k0 if k0 is not None else KNOWN_KIND.get(model_id)
    if kind is None:
        raise HxError('block kind for model %d unknown: pass --kind (amp 17)' % model_id)
    if params is None:
        params = p0 if p0 is not None else KNOWN_PARAMS.get(model_id)
    if params is None and k0 is None:
        params = kind_params(kind)       # a model no preset holds: its kind's knob layout (single cabs)
    if params is None:
        raise HxError('no parameter values known for model %d: pass --params v1,v2,...' % model_id)
    bl[i] = {19: BLOCK_TYPE, 20: {24: {23: False, 25: model_id, 26: -1}, 9: kind, 10: bool(enabled),
                                  11: {2: len(params), 3: len(params) - (kind in SHORT_COUNT_KINDS),
                                       4: list(params)},
                                  12: {2: 0, 3: 0, 4: []}}}
    _clear(bl, path, pos, clear_after, clear_path_b)
    check_position_free(sec, path, pos)
    return sec


def _clear(bl, path, pos, clear_after, clear_path_b):
    if clear_after:
        idxs = PATH_A_SLOTS if path == 0 else PATH_B_SLOTS
        for j in idxs[pos + 1:]:
            bl[j] = {19: EMPTY_TYPE, 20: None}
    if clear_path_b:
        for j in PATH_B_SLOTS:
            bl[j] = {19: EMPTY_TYPE, 20: None}


# --------------------------------------------------------------------------- JSON form

def to_json(o):
    """Lossless JSON form: dict keys -> strings, bytes -> {"$bin": hex}."""
    if isinstance(o, dict):
        return {str(k): to_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [to_json(v) for v in o]
    if isinstance(o, bytes):
        return {'$bin': o.hex()}
    return o


def from_json(o):
    if isinstance(o, dict):
        if set(o) == {'$bin'}:
            return bytes.fromhex(o['$bin'])
        return {(int(k) if k.lstrip('-').isdigit() else k): from_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [from_json(v) for v in o]
    return o


def clean_name(s):
    if isinstance(s, (bytes, bytearray)):
        s = s.decode('latin1')
    return s.split('\0')[0] if isinstance(s, str) else s


# --------------------------------------------------------------------------- USB session

class _Quiet:
    """Swallows hx_dfu_reboot's per-transfer prints unless verbose."""

    def __init__(self, verbose):
        self.verbose = verbose

    def __enter__(self):
        if self.verbose:
            return self
        self._ctx = contextlib.redirect_stdout(io.StringIO())
        self._ctx.__enter__()
        return self

    def __exit__(self, *a):
        if not self.verbose:
            self._ctx.__exit__(*a)


# Several streams share one USB link (HX Edit's editor, librarian and notify). hxu.Stream.poll
# drops whatever is not for the polling stream, so a notify message that arrives while the editor
# waits for its reply would be lost (and the device's notify sender then stalls on its window).
# Routed: every message goes to the stream it is for; every open stream keeps its heartbeat.
_STREAMS = []


def _routed_poll(self, timeout_ms=100):
    b = self.link.read(timeout_ms)
    for m in hxu.parse_in_transfer(b) if b else []:
        tgt = self
        if m['flags'] is not None:
            for s in _STREAMS:
                if s.link is self.link and (m['src'] & 0xFF) == (s.remote & 0xFF) and m['dst'] == s.local:
                    tgt = s
                    break
        if tgt is self:
            self._handle(m)
        else:
            try:
                tgt._handle(m)
            except hxu.ProtocolError as e:      # (another stream's trouble: that stream's, later)
                tgt.error = e
    now = time.monotonic()
    for s in [self] + [s for s in _STREAMS if s is not self and s.link is self.link]:
        if s.heartbeat and s.rx_seq is not None and now - s.last_tx >= hxu.HB_INTERVAL:
            s._send(hxu.F_HB, what='heartbeat')
    return bool(b)


hxu.Stream.poll = _routed_poll


class Channel:
    """One stream to a device service, with the select-service handshake done."""

    def __init__(self, link, local, remote, svc, verbose=False, timeout=3.0):
        self.link, self.svc, self.verbose, self.timeout = link, svc, verbose, timeout
        self.seq = 0
        self.log = []
        with _Quiet(verbose):
            self.st = hxu.Stream(link, local, remote, heartbeat=True)
            # the unit keeps a stream that was not closed until its heartbeat timeout
            # (~4 s); a new SYN is ignored meanwhile, so retry for a while
            for attempt in range(4):
                try:
                    self.st.connect(timeout)
                    break
                except hxu.ProtocolError:
                    if attempt == 3:
                        raise
                    self.st = hxu.Stream(link, local, remote, heartbeat=True)
            _STREAMS.append(self.st)
            self._write(struct.pack('<HHIB', 1, svc, 1, svc))
            a, s, body = self._read_msg(timeout)
        if body != bytes([svc]):
            raise HxError('service %d select: unexpected reply %r' % (svc, (a, s, body)))

    def _write(self, data):
        mx = (self.st.peer_mtu or 512) - 16
        for i in range(0, len(data), mx):
            self.st.write(data[i:i + mx], 'msg', self.timeout)

    def _read_msg(self, timeout):
        hdr = self.st.read(8, timeout, 'message header')
        a, s, ln = struct.unpack('<HHI', hdr)
        body = b''
        while len(body) < ln:
            body += self.st.read(min(ln - len(body), 0x400), timeout, 'message body')
            self.st.window_update()
        if not ln:
            self.st.window_update()
        return a, s, body

    def request(self, cmd, params=None, timeout=None, pending_wait=1.5):
        """Send {seq, cmd, params}; return the result (key 0x68) or raise HxError.
        Status 1 means "accepted, completes later": HX Edit
        keeps such a request pending and the completion arrives as a notification on the
        notify service (0x3F0), which this tool does not open. After a status-1 reply we
        wait pending_wait seconds for a final reply on this stream and otherwise return
        PENDING; callers verify the effect by reading state back."""
        timeout = timeout or self.timeout
        self.seq = (self.seq + 1) & 0xFFFF
        # HX Edit's packer writes L6Buffer values as MessagePack str (not bin); do the same
        req = msgpack.packb({K_SEQ: self.seq, K_CMD: cmd, K_PARAMS: params}, use_bin_type=False)
        with _Quiet(self.verbose):
            self._write(struct.pack('<HHI', 1, self.svc, len(req)) + req)
            a, s, body = self._read_msg(timeout)
        rep = msgpack.unpackb(body, raw=True, strict_map_key=False)    # strings/buffers -> bytes
        if not isinstance(rep, dict):
            raise HxError('cmd 0x%02x: reply is not a map: %r' % (cmd, rep))
        self.log.append((cmd, rep.get(K_SEQ), rep.get(K_STATUS)))
        if rep.get(K_STATUS) == 1:
            end = time.monotonic() + pending_wait
            with _Quiet(self.verbose):
                while time.monotonic() < end and len(self.st.rxbuf) < 8:
                    self.st.poll(50)
                if len(self.st.rxbuf) < 8:
                    return PENDING
                a, s, body = self._read_msg(timeout)
            rep = msgpack.unpackb(body, raw=True, strict_map_key=False)
            self.log.append((cmd, rep.get(K_SEQ), rep.get(K_STATUS)))
        if rep.get(K_STATUS) != 0:
            err = rep.get(K_RESULT, {}).get(K_ERR) if isinstance(rep.get(K_RESULT), dict) else None
            raise HxError('cmd 0x%02x refused: status %s, error %s' % (cmd, rep.get(K_STATUS), err))
        return rep.get(K_RESULT)

    def close(self):
        """Send FIN so the unit frees the port at once."""
        if self.st in _STREAMS:
            _STREAMS.remove(self.st)
        try:
            with _Quiet(self.verbose):
                self.st._send(hxu.F_FIN, what='FIN')
                self.st.sleep(0.2)
        except Exception:
            pass

    def drain(self, seconds):
        """Read every message that arrives within `seconds` (the notify stream); return them."""
        got = []
        end = time.monotonic() + seconds
        with _Quiet(self.verbose):
            while time.monotonic() < end:
                if len(self.st.rxbuf) < 8:
                    self.st.poll(50)
                    continue
                a, s, body = self._read_msg(self.timeout)
                try:
                    got.append(msgpack.unpackb(body, raw=True, strict_map_key=False))
                except Exception:
                    got.append(body)
        self.log += [('notify', m) for m in got]
        return got

    def idle(self, seconds):
        with _Quiet(self.verbose):
            self.st.sleep(seconds)


class HxCtl:
    """Session with the editor (and, on demand, librarian) service of a running HX Stomp."""

    def __init__(self, verbose=False, timeout=3.0, pid=None):
        self.verbose, self.timeout = verbose, timeout
        with _Quiet(verbose):
            self.link = hxu.UsbLink(pid, int(timeout * 1000), verbose)
            self.link.purge(0.5)
        self.ed = Channel(self.link, verbose=verbose, timeout=timeout, **EDITOR)
        self._lib = None
        # HX Edit keeps the notify stream open: 0x14/0x15 complete there, ~9 messages a preset write
        # (completion, block/footswitch/tempo changes). Unread, they piled up in the unit and it hung
        # on the 31st preset write a boot (stock too); read, 41 writes a boot passed (2026-11-01).
        # HX_NO_NOTIFY=1: without it (as before: then reboot within 30 writes)
        self.nf = None if os.environ.get('HX_NO_NOTIFY') else \
            Channel(self.link, verbose=verbose, timeout=timeout, **NOTIFY)
        self.notes = []

    def _complete(self, seconds=2.0):
        """Wait for (and consume) the notify stream's messages after a 0x14/0x15 request."""
        if self.nf is not None:
            self.notes += self.nf.drain(seconds)

    def close(self):
        if self.nf is not None:
            self.notes += self.nf.drain(0.2)
        if os.environ.get('HX_SHOW_NOTIFY'):
            print('notify: %d message(s): %s' % (len(self.notes), [str(m)[:160] for m in self.notes]))
        for ch in (self._lib, self.ed, self.nf):
            if ch is not None:
                ch.close()
        self.link.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @property
    def lib(self):
        if self._lib is None:
            self._lib = Channel(self.link, verbose=self.verbose, timeout=self.timeout, **LIBRARIAN)
        return self._lib

    # -- editor
    def current(self):
        r = self.ed.request(CMD_GET_CURRENT)
        return dict(setlist=r.get(K_SETLIST), preset=r.get(K_PRESET), name=clean_name(r.get(K_NAME)),
                    raw={str(k): to_json(v) for k, v in r.items()})

    def select(self, preset, setlist=None, settle=0.5):
        if setlist is None:
            setlist = self.current()['setlist']
        self.ed.request(CMD_LOAD_PRESET, {K_SETLIST: setlist, K_PRESET: preset}, timeout=max(self.timeout, 10))
        self._complete(max(settle, 1.0)) if self.nf is not None else self.ed.idle(settle)
        return self.current()

    def get_preset_blob(self):
        r = self.ed.request(CMD_GET_EDITBUF, timeout=max(self.timeout, 5))
        if not isinstance(r, (bytes, bytearray)):
            raise HxError('get edit buffer: unexpected result %r' % type(r))
        return bytes(r)

    def get_preset(self):
        return decode_preset(self.get_preset_blob())

    def set_preset_blob(self, blob, settle=0.5):
        decode_preset(blob)                                   # refuse anything that isn't a preset
        self.ed.request(CMD_SET_EDITBUF, {K_PBLOB: blob}, timeout=max(self.timeout, 10))
        self._complete(max(settle, 1.0)) if self.nf is not None else self.ed.idle(settle)

    def move_block(self, src, dst, settle=0.5):
        """Move the block at grid position src (a preset[0][22] index) to dst, as HX Edit does."""
        self.ed.request(CMD_MOVE_BLOCK, {K_MOVE_FROM: src, K_MOVE_TO: dst}, timeout=max(self.timeout, 10))
        self._complete(max(settle, 1.0)) if self.nf is not None else self.ed.idle(settle)

    # -- librarian
    def preset_list(self, setlist=None):
        if setlist is None:
            setlist = self.current()['setlist']
        return self.lib.request(CMD_LIB_PRESET_LIST, {K_SETLIST: setlist}, timeout=max(self.timeout, 5))


def midi_program_change(program, channel=0, port_name='HX Stomp'):
    import mido
    names = [n for n in mido.get_output_names() if port_name.lower() in n.lower()]
    if not names:
        raise HxError('no MIDI output named like %r (have: %s)' % (port_name, mido.get_output_names()))
    with mido.open_output(names[0]) as out:
        out.send(mido.Message('program_change', channel=channel, program=program))
    return names[0]


# --------------------------------------------------------------------------- CLI

def _parse_slot(s, sec=None):
    """POS | PATH:POS | end | PATH:end ('end' = the slot after the last used one)."""
    p, q = s.split(':', 1) if ':' in s else ('0', s)
    path = int(p)
    if q == 'end':
        if sec is None:
            raise HxError('--slot end needs the preset')
        pos = last_used_pos(sec, path) + 1
        if pos > 7:
            raise HxError('path %d is full' % path)
        return path, pos
    return path, int(q)


def _print_summary(sec, cur=None):
    if cur:
        print('setlist %s preset %s "%s"' % (cur['setlist'], cur['preset'], cur['name']))
    bl = summarize(sec)
    if not bl:
        print('  (no blocks)')
    for b in bl:
        print('  path %d slot %d: model %s kind %s %s params %s' % (
            b['path'], b['slot'], b['model_id'], b['kind'], 'on' if b['enabled'] else 'off', b['params']))


def preset_names(lst):
    """Librarian cmd 0x01 result [{index: {0x6d: name, 0x7b, 0x7c, 0x7d}}, ...] -> [(index, name)]."""
    out = []
    for e in lst or []:
        if isinstance(e, dict):
            for idx, info in e.items():
                name = clean_name(info.get(K_NAME)) if isinstance(info, dict) else None
                out.append((idx, name))
    return sorted(out)


def parse_params(text):
    """Comma-separated knob values with their preset types: 5 -> int, 0.5 -> float,
    true/false -> bool. The unit keeps types: a knob given the wrong type drops the whole
    preset (an integer knob given a float, and a float knob given 0 instead of 0.0, both did:
    NAM Lite Multi and kit-probe, 2026-10-28). Write floats with a point."""
    out = []
    for x in text.split(','):
        x = x.strip()
        if x.lower() in ('true', 'false'):
            out.append(x.lower() == 'true')
        elif re.fullmatch(r'[-+]?\d+', x):
            out.append(int(x))
        else:
            out.append(float(x))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--dry-run', action='store_true',
                    help='for writes: read from the unit (or --from-file) and print what would be sent; send nothing that changes state')
    ap.add_argument('--from-file', help='with --dry-run: use this preset (.json from get-preset or raw .bin) instead of the unit')
    ap.add_argument('--verbose', action='store_true', help='print every USB transfer')
    ap.add_argument('--timeout', type=float, default=3.0)
    ap.add_argument('--pid', type=lambda s: int(s, 0), default=None)
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('status', help='current setlist/preset/name and the blocks in the edit buffer')
    sp = sub.add_parser('select', help='load preset N (0-based) of the current or given setlist')
    sp.add_argument('preset', type=int)
    sp.add_argument('--setlist', type=int)
    sp.add_argument('--midi', action='store_true', help='send a USB-MIDI Program Change instead (setlist untouched)')
    sp.add_argument('--midi-channel', type=int, default=1, help='1-16 (default 1)')
    sp = sub.add_parser('presets', help='list preset names of the current or given setlist')
    sp.add_argument('--setlist', type=int)
    sp.add_argument('--raw', action='store_true')
    sp = sub.add_parser('get-preset', help='dump the edit buffer as JSON (and optionally the raw blob)')
    sp.add_argument('-o', '--output', help='JSON file (default stdout)')
    sp.add_argument('--bin', help='also write the raw l6-helix blob here')
    sp = sub.add_parser('load-preset', help='write a preset (JSON from get-preset, or raw .bin) into the edit buffer')
    sp.add_argument('file')
    sp = sub.add_parser('set-model', help='put a model (Table 1 preset_id) into a block slot of the edit buffer')
    sp.add_argument('--slot', required=True, help='POS (path A, 0..7), PATH:POS, or end / PATH:end (after the last position used on either path: the paths share 8 positions)')
    sp.add_argument('--model-id', type=int, required=True)
    sp.add_argument('--params', help='comma-separated values (default: copied from a block with this model in the preset)')
    sp.add_argument('--kind', type=int, help='block kind (body key 9); default from the preset or a known table')
    sp.add_argument('--cab-id', type=int, help='a block with a cab half: a dual cab\'s second cab or an amp\'s cab '
                    '(a single cab needs none; cab blocks are copied from a factory block of the same model)')
    sp.add_argument('--disabled', action='store_true')
    sp.add_argument('--clear-after', action='store_true', help='empty the later slots on the same path')
    sp.add_argument('--clear-path-b', action='store_true', help='also empty every slot on path B')
    sp.add_argument('--save-before', help='write the edit buffer before the change here (JSON)')
    sp = sub.add_parser('move', help='move a block to another slot (HX Edit\'s drag; the unit rebuilds the chain)')
    sp.add_argument('--from', dest='src', required=True, help='PATH:POS or POS (path A)')
    sp.add_argument('--to', dest='dst', required=True, help='PATH:POS or POS (path A)')
    args = ap.parse_args(argv)

    def load_file(path):
        d = open(path, 'rb').read()
        if d[:1] == b'{':
            j = json.loads(d)
            if 'preset' in j:
                return j.get('magic', 'l6-helix\0'), from_json(j['preset'])
            raise HxError('%s: no "preset" key' % path)
        return decode_preset(d)

    # ---- offline dry runs
    if args.dry_run and args.from_file and args.cmd in ('set-model', 'load-preset'):
        if args.cmd == 'set-model':
            magic, sec = load_file(args.from_file)
            path, pos = _parse_slot(args.slot, sec)
            params = parse_params(args.params) if args.params else None
            try:
                set_model(sec, path, pos, args.model_id, params, args.kind, not args.disabled,
                          args.clear_after, args.clear_path_b, args.cab_id)
            except HxError as e:
                sys.exit('error: %s' % e)
        else:
            magic, sec = load_file(args.file)
        blob = encode_preset(magic, sec)
        print('[dry-run] would send cmd 0x15 with a %d-byte preset:' % len(blob))
        _print_summary(sec)
        return 0

    if args.cmd == 'select' and args.midi:
        prog = args.preset
        if args.dry_run:
            print('[dry-run] would send MIDI Program Change %d on channel %d' % (prog, args.midi_channel))
            return 0
        port = midi_program_change(prog, args.midi_channel - 1)
        print('sent Program Change %d ch %d to %s' % (prog, args.midi_channel, port))
        try:
            with HxCtl(args.verbose, args.timeout, args.pid) as hx:
                hx.ed.idle(0.7)
                c = hx.current()
                print('now: setlist %s preset %s "%s"' % (c['setlist'], c['preset'], c['name']))
        except (HxError, hxu.ProtocolError, SystemExit) as e:
            print('(could not read back over USB: %s)' % e)
        return 0

    try:
        hx = HxCtl(args.verbose, args.timeout, args.pid)
    except hxu.ProtocolError as e:
        sys.exit('error: %s' % e)
    try:
        if args.cmd == 'status':
            c = hx.current()
            magic, sec = hx.get_preset()
            _print_summary(sec, c)
        elif args.cmd == 'select':
            if args.dry_run:
                c = hx.current()
                print('[dry-run] now at setlist %s preset %s; would send cmd 0x14 {setlist %s, preset %d}'
                      % (c['setlist'], c['preset'], c['setlist'] if args.setlist is None else args.setlist,
                         args.preset))
            else:
                c = hx.select(args.preset, args.setlist)
                print('now: setlist %s preset %s "%s"' % (c['setlist'], c['preset'], c['name']))
                if c['preset'] != args.preset:
                    sys.exit('error: the unit reports preset %s, not %d' % (c['preset'], args.preset))
        elif args.cmd == 'presets':
            r = hx.preset_list(args.setlist)
            if args.raw:
                print(json.dumps(to_json(r), indent=1))
            else:
                for i, name in preset_names(r):
                    print('%3d  %s' % (i, name))
        elif args.cmd == 'get-preset':
            c = hx.current()
            blob = hx.get_preset_blob()
            magic, sec = decode_preset(blob)
            out = dict(setlist=c['setlist'], preset_index=c['preset'], name=c['name'], magic=magic,
                       blocks=summarize(sec), preset=to_json(sec))
            s = json.dumps(out, indent=1)
            if args.output:
                open(args.output, 'w').write(s + '\n')
                print('wrote %s (%d-byte blob)' % (args.output, len(blob)))
                _print_summary(sec, c)
            else:
                print(s)
            if args.bin:
                open(args.bin, 'wb').write(blob)
        elif args.cmd == 'move':
            (sp_, sq), (dp, dq) = _parse_slot(args.src), _parse_slot(args.dst)
            magic, before = hx.get_preset()
            e = blocks(before)[slot_index(sp_, sq)]
            mid = e.get(20, {}).get(24, {}).get(25) if isinstance(e.get(20), dict) else None
            if mid is None:
                raise HxError('no block at path %d slot %d' % (sp_, sq))
            if (dp, dq) != (sp_, sq) and dq != sq:
                check_position_free(before, dp, dq)
            if _used(blocks(before), slot_index(dp, dq)) and (dp, dq) != (sp_, sq):
                raise HxError('path %d slot %d holds a block: cmd 0x2b onto a used slot replaces it' % (dp, dq))
            if args.dry_run:
                print('[dry-run] would send cmd 0x2b {from %d, to %d} (model %d)'
                      % (slot_index(sp_, sq), slot_index(dp, dq), mid))
                return 0
            hx.move_block(slot_index(sp_, sq), slot_index(dp, dq))
            got_magic, got = hx.get_preset()
            print('edit buffer after move:')
            _print_summary(got, hx.current())
            had = sorted(b['model_id'] for b in summarize(before))
            has = sorted(b['model_id'] for b in summarize(got))
            if had != has:
                sys.exit('error: blocks before %s, after %s: the move lost or added a block' % (had, has))
            print('verified: same blocks (%s), model %d moved' % (has, mid))
        elif args.cmd in ('load-preset', 'set-model'):
            before_blob = hx.get_preset_blob()
            if args.cmd == 'load-preset':
                magic, sec = load_file(args.file)
            else:
                magic, sec = decode_preset(before_blob)
                if args.save_before:
                    c = hx.current()
                    open(args.save_before, 'w').write(json.dumps(dict(
                        setlist=c['setlist'], preset_index=c['preset'], name=c['name'], magic=magic,
                        blocks=summarize(sec), preset=to_json(sec)), indent=1) + '\n')
                path, pos = _parse_slot(args.slot, sec)
                params = parse_params(args.params) if args.params else None
                set_model(sec, path, pos, args.model_id, params, args.kind, not args.disabled,
                          args.clear_after, args.clear_path_b, args.cab_id)
            blob = encode_preset(magic, sec, like=before_blob)
            if args.dry_run:
                print('[dry-run] would send cmd 0x15 with a %d-byte preset (unit now holds %d bytes):'
                      % (len(blob), len(before_blob)))
                _print_summary(sec)
                return 0
            hx.set_preset_blob(blob)
            got_magic, got = hx.get_preset()
            print('edit buffer after write:')
            _print_summary(got, hx.current())
            if args.cmd == 'set-model':
                e = blocks(got)[slot_index(path, pos)]
                mid = e.get(20, {}).get(24, {}).get(25) if isinstance(e.get(20), dict) else None
                if mid != args.model_id:
                    hint = (' The edit buffer came back empty: the unit dropped the preset (a third'
                            ' kind-17 block, amp or preamp, does that; or over the DSP budget).') if not summarize(got) else ''
                    sys.exit('error: read back model %s at that slot, not %d.%s' % (mid, args.model_id, hint))
                print('verified: model %d at path %d slot %d' % (mid, path, pos))
            elif summarize(got) != summarize(sec):
                sys.exit('error: read-back blocks differ from what was written')
            else:
                print('verified: read-back blocks match')
    except (HxError, hxu.ProtocolError) as e:
        sys.exit('error: %s' % e)
    finally:
        hx.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
