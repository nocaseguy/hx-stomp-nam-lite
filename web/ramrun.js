// ramrun.js - run a built firmware from the Stomp's RAM over WebUSB, the way
// tools/hxf_ram.py does from a desktop: nothing is written to the Stomp, and
// turning it off and on brings back what is installed (RAM_RUN.md).
//
//   1. a running Stomp (0e41:4246, or the XL's 4253) is asked to restart in
//      update mode, as Line 6 Updater does: its message stream to port 0xEF,
//      update command 2. A Stomp started with Page Right held skips this.
//   2. the boot ROM's DFU loader (1fc9:000c) gets the RAM loader,
//      tools/ramboot/firmware-ramboot.dfu, as dfu-util would send it.
//   3. the RAM loader (1209:0001) gets the regions hxf_ram.py's plan made
//      (firmware-worker.js runs it), checks each one's CRC in SDRAM, and
//      starts the firmware.
//
// RAMRUN.run(opts) does all three, from whichever stage the Stomp is in.
//   opts.plan     { regions: [{ addr, label, bytes: Uint8Array }], checks: [[first, count, crc, entry]] }
//   opts.loader   Uint8Array, the .dfu image
//   opts.usb      navigator.usb (or a stand-in, for tests/test_ramrun.py)
//   opts.ask(stage) -> Promise, resolved from a click (the browser may then ask
//                 for the device: "dfu" | "loader"); opts.unask() when not needed
//                 after all
//   opts.stage(stage), opts.progress(fraction, label), opts.log(text)
//   opts.sleep(ms) -> Promise (optional; tests make it instant)
// It resolves when the firmware has started and rejects with an Error whose
// .code names what went wrong (see CODES).
(function (root) {
  "use strict";

  var LINE6 = [{ vendorId: 0x0E41, productId: 0x4246 }, { vendorId: 0x0E41, productId: 0x4253 }];
  var DFU = [{ vendorId: 0x1FC9, productId: 0x000C }];
  var LOADER = [{ vendorId: 0x1209, productId: 0x0001 }];

  // src/ramboot/ramboot.h (tools/hxf_ram.py keeps a copy too: keep the three the same)
  var RB = {
    VERSION: 1, HOOK_BASE: 0x29000000, STAGE_BASE: 0x29E00000, DESC: 0x29EFF000, FREE_END: 0x29F00000,
    REQ_INFO: 0x20, REQ_ADDR: 0x21, REQ_DATA: 0x22, REQ_LEN: 0x23, REQ_CRC: 0x24, REQ_EMMC_CRC: 0x25,
    REQ_GO: 0x26, GO_KEY: 0x60B0, CHUNK: 4096
  };

  // Error codes the page turns into words.
  var CODES = ["busy", "line6", "dfu", "loader", "sdram", "crc", "emmc", "go", "gone", "cancel"];

  function fail(code, text) { var e = new Error(text); e.code = code; return e; }
  function hex(n, w) { return "0x" + (n >>> 0).toString(16).padStart(w || 8, "0"); }
  function realSleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  var CRC_TABLE = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(b) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < b.length; i++) c = CRC_TABLE[(c ^ b[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function match(dev, filters) {
    return filters.some(function (f) { return dev.vendorId === f.vendorId && dev.productId === f.productId; });
  }

  // ---- 1. Restart in update mode (tools/hx_dfu_reboot.py in the private notes; Line 6 Updater's
  //         "Rebooting into NX bootloader"). Transport header: type<<28 | 2<<26 | length, src | dst<<16;
  //         stream header: flags<<24 | seq<<8, the receive-window edge.
  var LOCAL = 0x1001, REMOTE = 0x03EF, RX_BUF = 0x1000;
  var F_SYN = 0x01, F_FIN = 0x02, F_DATA = 0x04, F_WIN = 0x08, F_HB = 0x10, F_HBREQ = 0x20;

  function concat(parts) {
    var n = parts.reduce(function (s, p) { return s + p.length; }, 0);
    var out = new Uint8Array(n), o = 0;
    parts.forEach(function (p) { out.set(p, o); o += p.length; });
    return out;
  }
  function words(list) {
    var b = new Uint8Array(4 * list.length), v = new DataView(b.buffer);
    list.forEach(function (w, i) { v.setUint32(4 * i, w >>> 0, true); });
    return b;
  }
  function pad4(b) { return b.length % 4 ? concat([b, new Uint8Array(4 - b.length % 4)]) : b; }

  function parseIn(buf) {
    var out = [], off = 0, v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    while (off + 8 <= buf.length) {
      var w0 = v.getUint32(off, true), w1 = v.getUint32(off + 4, true);
      var type = w0 >>> 28, len = w0 & 0xFFFF;
      if (off + 8 + len > buf.length) throw fail("line6", "truncated message from the Stomp");
      var m = { type: type, src: w1 & 0xFFFF, dst: w1 >>> 16, flags: null }, p = off + 8;
      if (type === 2) { m.mtu = v.getUint32(p, true) >>> 16; p += 4; }
      if (off + 8 + len - p >= 8) {
        var s0 = v.getUint32(p, true);
        m.flags = s0 >>> 24; m.seq = (s0 >>> 8) & 0xFF; m.window = v.getUint32(p + 4, true);
        m.data = buf.slice(p + 8, off + 8 + len);
      }
      out.push(m);
      off += (8 + len + 3) & ~3;
    }
    return out;
  }

  function Stream(dev, epOut, epIn, mtu, sleep, log) {
    this.dev = dev; this.epOut = epOut; this.epIn = epIn; this.mtu = mtu; this.sleep = sleep; this.log = log;
    this.txSeq = 1; this.rxSeq = null; this.consumed = 0; this.sent = 0; this.peerWindow = 0;
    this.rx = new Uint8Array(0); this.queue = []; this.waiter = null; this.closed = false; this.lastTx = Date.now();
  }
  Stream.prototype.startReading = function () {
    var self = this;
    (function next() {
      if (self.closed) return;
      self.dev.transferIn(self.epIn, self.mtu).then(function (r) {
        if (r.data && r.data.byteLength) {
          self.queue.push(new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength).slice());
          if (self.waiter) { var w = self.waiter; self.waiter = null; w(); }
        }
        next();
      }, function () { self.closed = true; if (self.waiter) { var w = self.waiter; self.waiter = null; w(); } });
    })();
  };
  Stream.prototype.next = function (ms) {        // the next IN transfer, or null after ms
    var self = this;
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    if (this.closed) return Promise.resolve(null);
    return new Promise(function (resolve) {
      var done = false;
      function finish() { if (done) return; done = true; self.waiter = null; resolve(self.queue.length ? self.queue.shift() : null); }
      self.waiter = finish;
      self.sleep(ms).then(finish);
    });
  };
  Stream.prototype.send = function (flags, data, what) {
    data = data || new Uint8Array(0);
    var sh = words([(flags << 24) | (this.txSeq << 8), RX_BUF + this.consumed]), body, type;
    if (flags & F_SYN) { body = concat([words([(this.mtu & 0xFFFF) << 16]), sh, data]); type = 2; }
    else { body = concat([sh, data]); type = 1; }
    var msg = pad4(concat([words([(type << 28) | (2 << 26) | body.length, LOCAL | ((REMOTE & 0x3FF) << 16)]), body]));
    this.txSeq = (this.txSeq + 1) & 0xFF;
    this.sent += data.length;
    this.lastTx = Date.now();
    this.log("out " + what + "\n");
    return this.dev.transferOut(this.epOut, msg).then(function (r) {
      if (r && r.status && r.status !== "ok") throw fail("line6", "bulk OUT " + r.status);
    });
  };
  Stream.prototype.handle = function (m) {
    if (m.flags === null || (m.src & 0xFF) !== (REMOTE & 0xFF) || m.dst !== LOCAL) return;
    if (m.flags & F_SYN) {
      if (this.rxSeq !== null) throw fail("line6", "unexpected SYN from the Stomp");
      this.rxSeq = m.seq; this.peerWindow = m.window;
      return;
    }
    if (this.rxSeq === null) throw fail("line6", "the Stomp answered before connecting");
    if (((m.seq - this.rxSeq) & 0xFF) !== 1) throw fail("line6", "sequence gap from the Stomp");
    this.rxSeq = m.seq;
    if (m.flags & (F_DATA | F_WIN)) {
      this.peerWindow = m.window;
      if (m.flags & F_DATA && m.data.length) this.rx = concat([this.rx, m.data]);
    }
    if (m.flags & F_FIN) throw fail("line6", "the Stomp closed the stream: it refused the request");
  };
  Stream.prototype.poll = function (ms) {
    var self = this;
    return this.next(ms).then(function (b) {
      if (b) parseIn(b).forEach(function (m) { self.handle(m); });
      if (self.rxSeq !== null && Date.now() - self.lastTx >= 1000) return self.send(F_HB, null, "heartbeat");
    });
  };
  Stream.prototype.until = function (cond, seconds, what) {
    var self = this, end = Date.now() + seconds * 1000;
    return (function loop() {
      if (cond()) return Promise.resolve();
      if (Date.now() > end || self.closed) return Promise.reject(fail("line6", "no answer from the Stomp (" + what + ")"));
      return self.poll(100).then(loop);
    })();
  };
  Stream.prototype.write = function (data, what) {
    var self = this;
    return this.until(function () { return self.sent + data.length <= self.peerWindow; }, 3, "window")
      .then(function () { return self.send(F_DATA, data, what); });
  };
  Stream.prototype.read = function (n, what) {
    var self = this;
    return this.until(function () { return self.rx.length >= n; }, 3, what).then(function () {
      var out = self.rx.slice(0, n);
      self.rx = self.rx.slice(n);
      self.consumed += n;
      return out;
    });
  };

  function u16u16u32(a, b, c) {
    var x = new Uint8Array(8), v = new DataView(x.buffer);
    v.setUint16(0, a, true); v.setUint16(2, b, true); v.setUint32(4, c, true);
    return x;
  }

  async function rebootToDfu(dev, o) {
    await dev.open();
    if (!dev.configuration) await dev.selectConfiguration(1);
    var intf = dev.configuration.interfaces.filter(function (i) { return i.interfaceNumber === 0; })[0];
    var alt = intf && (intf.alternate || intf.alternates[0]);
    var bulk = alt ? alt.endpoints.filter(function (e) { return e.type === "bulk"; }) : [];
    if (!alt || alt.interfaceClass !== 0xFF || bulk.length !== 2) throw fail("line6", "interface 0 is not the Stomp's message interface");
    try { await dev.claimInterface(0); }
    catch (e) { try { await dev.close(); } catch (e2) { /* closed */ } throw fail("busy", "cannot claim interface 0: " + e.message); }
    var epIn = bulk.filter(function (e) { return e.direction === "in"; })[0];
    var epOut = bulk.filter(function (e) { return e.direction === "out"; })[0];
    var st = new Stream(dev, epOut.endpointNumber, epIn.endpointNumber, epIn.packetSize, o.sleep, o.log);
    o.log("Stomp " + hex(dev.productId, 4) + ": interface 0, OUT " + epOut.endpointNumber + ", IN " +
          epIn.endpointNumber + ", mtu " + epIn.packetSize + "\n");
    try {
      st.startReading();
      var end = Date.now() + 1000;                  // Line 6 Updater drops what is waiting for ~1 s first
      while (Date.now() < end && !st.closed) { await st.next(100); st.queue = []; }
      await st.send(F_SYN | F_HBREQ, null, "SYN");
      await st.until(function () { return st.rxSeq !== null; }, 3, "connect");
      await st.write(concat([u16u16u32(0, 3, 1), new Uint8Array([3])]), "select service 3");
      var t = Date.now() + 425;
      while (Date.now() < t) await st.poll(50);
      await st.write(concat([u16u16u32(1, 0, 2), new Uint8Array(2)]), "version");
      var h = await st.read(8, "hello");
      if (new DataView(h.buffer).getUint32(4, true) !== 2) throw fail("line6", "not the stock update service");
      await st.read(2, "hello");
      await st.send(F_WIN, null, "window update");
      await st.write(new Uint8Array([0xAA, 0, 0, 1]), "QueryUpdateProtocolInfo");
      var pi = await st.read(4, "protocol info");
      if (pi[0] >= 2 || [pi[1], pi[2], pi[3]].some(function (x) { return x < 1 || x > 4; })) {
        throw fail("line6", "unexpected protocol info " + Array.from(pi).join(" "));
      }
      await st.send(F_WIN, null, "window update");
      await st.write(new Uint8Array([0xAA, 0, 0, 3]), "QueryDeviceInfo");
      await st.read(36, "device info");
      await st.send(F_WIN, null, "window update");
      await st.write(new Uint8Array([0xAA, 0, 0, 2]), "EnterUpdateMode");
      var res = new DataView((await st.read(4, "result")).buffer).getInt32(0, true);
      if (res < 0) throw fail("line6", "the Stomp refused update mode (" + res + ")");
      o.log("the Stomp restarts in update mode\n");
    } finally {
      st.closed = true;
      try { await dev.releaseInterface(0); } catch (e) { /* it is resetting */ }
      try { await dev.close(); } catch (e) { /* it is resetting */ }
    }
  }

  // ---- 2. The RAM loader into the boot ROM's DFU loader (DFU 1.1, as dfu-util sends it).
  var DNLOAD = 1, GETSTATUS = 3, CLRSTATUS = 4, DNLOAD_IDLE = 5, DFU_ERROR = 10;

  async function dfuTransferSize(dev) {
    try {
      var r = await dev.controlTransferIn({ requestType: "standard", recipient: "device", request: 6, value: 0x0200, index: 0 }, 512);
      var b = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
      for (var i = 0; i + 1 < b.length && b[i]; i += b[i]) {
        if (b[i + 1] === 0x21 && b[i] >= 7) return b[i + 5] | (b[i + 6] << 8);
      }
    } catch (e) { /* fall back */ }
    return 2048;
  }

  async function dfuLoad(dev, image, o) {
    await dev.open();
    if (!dev.configuration) await dev.selectConfiguration(1);
    await dev.claimInterface(0);
    var setup = function (req, value) { return { requestType: "class", recipient: "interface", request: req, value: value, index: 0 }; };
    async function status() {
      var r = await dev.controlTransferIn(setup(GETSTATUS, 0), 6);
      var d = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
      return { status: d[0], poll: d[1] | (d[2] << 8) | (d[3] << 16), state: d[4] };
    }
    var s = await status();
    if (s.state === DFU_ERROR) { await dev.controlTransferOut(setup(CLRSTATUS, 0)); await status(); }
    var size = await dfuTransferSize(dev);
    o.log("DFU: " + image.length + " bytes in blocks of " + size + "\n");
    var block = 0;
    for (var off = 0; off < image.length; off += size, block++) {
      await dev.controlTransferOut(setup(DNLOAD, block), image.slice(off, off + size));
      for (;;) {
        s = await status();
        if (s.status !== 0) throw fail("dfu", "DFU status " + s.status + " (state " + s.state + ") at block " + block);
        if (s.state === DNLOAD_IDLE) break;
        await o.sleep(Math.max(s.poll, 1));
      }
      o.progress(Math.min(1, (off + size) / image.length), "dfu");
    }
    try {
      await dev.controlTransferOut(setup(DNLOAD, block), new Uint8Array(0));
      await status();                              // the ROM starts the image and leaves USB here
    } catch (e) { /* expected */ }
    try { await dev.close(); } catch (e) { /* gone */ }
    o.log("DFU: the RAM loader is running\n");
  }

  // ---- 3. The firmware into SDRAM, through the RAM loader (src/ramboot/ramboot.c).
  async function loaderRun(dev, plan, o) {
    await dev.open();
    try { if (!dev.configuration) await dev.selectConfiguration(1); } catch (e) { /* it has one */ }
    try { await dev.claimInterface(0); } catch (e) { /* control requests to the device need none */ }
    var vin = function (req, value, index, n) {
      return dev.controlTransferIn({ requestType: "vendor", recipient: "device", request: req, value: value, index: index }, n)
        .then(function (r) {
          if (r.status !== "ok") throw fail("loader", "request " + hex(req, 2) + ": " + r.status);
          return new DataView(r.data.buffer, r.data.byteOffset, r.data.byteLength);
        });
    };
    var vout = function (req, arg, data) {
      return dev.controlTransferOut({ requestType: "vendor", recipient: "device", request: req,
                                      value: arg & 0xFFFF, index: arg >>> 16 }, data)
        .then(function (r) { if (r.status !== "ok") throw fail("loader", "request " + hex(req, 2) + ": " + r.status); });
    };

    var info = await vin(RB.REQ_INFO, 0, 0, 64);
    var magic = String.fromCharCode(info.getUint8(0), info.getUint8(1), info.getUint8(2), info.getUint8(3));
    var f = []; for (var i = 0; i < 12; i++) f.push(info.getUint32(4 + 4 * i, true));
    if (magic !== "RAMB") throw fail("loader", "the device on USB is not the RAM loader");
    if (f[0] !== RB.VERSION || f[7] !== RB.HOOK_BASE || f[8] !== RB.STAGE_BASE || f[9] !== RB.DESC ||
        f[10] !== RB.FREE_END || f[11] !== RB.CHUNK) throw fail("loader", "the RAM loader is another version than this page's");
    if (!(f[1] & 1)) throw fail("sdram", "the RAM loader's SDRAM test failed at " + hex(f[6]));
    o.log("RAM loader v" + f[0] + ": core " + f[2] + " MHz, EMC " + f[3] + " MHz, eMMC " +
          (f[1] & 2 ? f[5] + " sectors" : "not started (status " + hex(f[4], 3) + ")") + "\n");

    var total = plan.regions.reduce(function (s, r) { return s + r.bytes.length; }, 0), done = 0;
    if (plan.checks.length && f[1] & 2) {
      o.stage("emmc");
      for (var k = 0; k < plan.checks.length; k++) {
        var c = plan.checks[k];
        await vout(RB.REQ_LEN, c[1]);
        var r = await vin(RB.REQ_EMMC_CRC, c[0] & 0xFFFF, c[0] >>> 16, 8);
        if (r.getUint32(4, true)) throw fail("emmc", "eMMC read failed at sector " + hex(c[0]));
        if (r.getUint32(0, true) !== c[2] >>> 0) {
          throw fail("emmc", "entry " + c[3] + " on the Stomp is not the stock 3.80.0 firmware the build was made from");
        }
        o.progress((k + 1) / plan.checks.length, "emmc");
      }
      o.log("eMMC: the installed firmware matches stock 3.80.0 where the RAM run reads it\n");
    } else if (plan.checks.length) {
      o.log("eMMC: not checked (the RAM loader could not start it)\n");
    }

    o.stage("upload");
    for (var n = 0; n < plan.regions.length; n++) {
      var reg = plan.regions[n], b = reg.bytes;
      await vout(RB.REQ_ADDR, reg.addr);
      for (var off = 0; off < b.length; off += RB.CHUNK) {
        await vout(RB.REQ_DATA, 0, b.subarray(off, off + RB.CHUNK));
        done += Math.min(RB.CHUNK, b.length - off);
        if ((off / RB.CHUNK) % 16 === 0 || off + RB.CHUNK >= b.length) o.progress(done / total, "upload");
      }
      await vout(RB.REQ_ADDR, reg.addr);
      await vout(RB.REQ_LEN, b.length);
      var got = (await vin(RB.REQ_CRC, 0, 0, 4)).getUint32(0, true);
      if (got !== crc32(b)) throw fail("crc", reg.label + ": CRC in SDRAM " + hex(got) + ", sent " + hex(crc32(b)));
      o.log(reg.label + " at " + hex(reg.addr) + ": " + Math.round(b.length / 1024) + " KiB, CRC ok\n");
    }

    o.stage("start");
    try { await vout(RB.REQ_GO, RB.GO_KEY); } catch (e) { /* it may leave USB before the status stage */ }
    try { await dev.close(); } catch (e) { /* gone */ }
  }

  // ---- The whole run --------------------------------------------------------------------------
  async function present(usb, filters) {
    var list = await usb.getDevices();
    return list.filter(function (d) { return match(d, filters); })[0] || null;
  }

  // The device for a stage: one the page may already use, as soon as it comes up, or the one
  // the person picks in the browser's list after clicking (opts.ask, shown at once; opts.unask
  // takes the button away if the device turns up by itself first).
  async function find(o, filters, stage, seconds) {
    var clicked = false, end = Date.now() + seconds * 1000;
    o.ask(stage).then(function () { clicked = true; });
    for (;;) {
      var d = await present(o.usb, filters);
      if (d) { if (o.unask) o.unask(); return d; }
      if (clicked) break;
      if (Date.now() > end) throw fail("gone", "the Stomp did not come back as the " + stage + " device");
      await o.sleep(250);
    }
    try { return await o.usb.requestDevice({ filters: filters }); }
    catch (e) { throw fail("cancel", "no device chosen (" + stage + ")"); }
  }

  async function gone(o, dev, seconds) {
    var end = Date.now() + seconds * 1000;
    while (Date.now() < end) {
      var list = await o.usb.getDevices();
      if (list.indexOf(dev) < 0) return true;
      await o.sleep(200);
    }
    return false;
  }

  async function run(o) {
    o.sleep = o.sleep || realSleep;
    o.log = o.log || function () {};
    o.progress = o.progress || function () {};
    o.stage = o.stage || function () {};
    var dev = (await present(o.usb, LOADER)) || (await present(o.usb, DFU)) || (await present(o.usb, LINE6));
    if (!dev) {
      try { dev = await o.usb.requestDevice({ filters: LINE6.concat(DFU, LOADER) }); }
      catch (e) { throw fail("cancel", "no device chosen"); }
    }
    if (match(dev, LINE6)) {
      o.stage("reboot");
      await rebootToDfu(dev, o);
      dev = await find(o, DFU, "dfu", 60);
    }
    if (match(dev, DFU)) {
      o.stage("dfu");
      await dfuLoad(dev, o.loader, o);
      dev = await find(o, LOADER, "loader", 60);
    }
    o.stage("loader");
    await loaderRun(dev, o.plan, o);
    if (!(await gone(o, dev, 5))) throw fail("go", "the RAM loader is still on USB: it refused to start the firmware");
    o.log("started: the firmware runs from RAM; turn the Stomp off and on to go back\n");
  }

  var api = { run: run, crc32: crc32, parseIn: parseIn, RB: RB, CODES: CODES, LINE6: LINE6, DFU: DFU, LOADER: LOADER };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RAMRUN = api;
})(typeof self !== "undefined" ? self : this);
