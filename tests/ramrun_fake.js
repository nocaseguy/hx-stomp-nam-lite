// ramrun_fake.js - web/ramrun.js against stand-ins for the three USB devices it talks to:
// a running Stomp (its update service on port 0xEF, played from what the stock app does),
// the boot ROM's DFU loader, and the RAM loader (src/ramboot/ramboot.c's requests).
// tests/test_ramrun.py runs it: node ramrun_fake.js <ramrun.js> <scenario>; prints a JSON report.
"use strict";
const RAMRUN = require(process.argv[2]);
const scenario = process.argv[3];

const report = { ask: [], stages: [], dfu: null, loaderWrites: 0, go: false, errors: [] };
function check(cond, what) { if (!cond) report.errors.push(what); }
function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }
function put32(b, o, v) { b[o] = v & 255; b[o + 1] = (v >>> 8) & 255; b[o + 2] = (v >>> 16) & 255; b[o + 3] = (v >>> 24) & 255; }

class Usb {
  constructor() { this.devices = []; this.allowed = new Set(); }
  async getDevices() { return this.devices.filter((d) => this.allowed.has(d)); }
  async requestDevice(opts) {
    const d = this.devices.find((x) => opts.filters.some((f) => f.vendorId === x.vendorId && f.productId === x.productId));
    if (!d) throw new Error("NotFoundError");
    this.allowed.add(d);
    return d;
  }
  plug(d, allowed) { this.devices.push(d); if (allowed) this.allowed.add(d); }
  unplug(d) { this.devices = this.devices.filter((x) => x !== d); d.gone = true; }
}
const usb = new Usb();

class Dev {
  constructor(vid, pid, intf) {
    this.vendorId = vid; this.productId = pid; this.configuration = null; this.opened = false; this.gone = false;
    this.cfg = { interfaces: [{ interfaceNumber: 0, alternate: intf, alternates: [intf] }] };
  }
  async open() { if (this.gone) throw new Error("gone"); this.opened = true; }
  async selectConfiguration() { this.configuration = this.cfg; }
  async claimInterface() { if (this.gone) throw new Error("gone"); }
  async releaseInterface() {}
  async close() { this.opened = false; }
}

// ---- the running Stomp: transport + stream framing as in tools/hx_dfu_reboot.py's DryLink
class Line6 extends Dev {
  constructor(busy) {
    super(0x0E41, 0x4246, { interfaceClass: 0xFF, endpoints: [
      { endpointNumber: 1, direction: "out", type: "bulk", packetSize: 512 },
      { endpointNumber: 1, direction: "in", type: "bulk", packetSize: 512 }] });
    this.configuration = this.cfg;            // a running Stomp is configured
    this.busy = busy; this.q = []; this.wait = null; this.seq = 0; this.hostSeq = 0; this.rx = []; this.stage = 0;
  }
  async claimInterface() { if (this.busy) throw new Error("Unable to claim interface."); }
  queue(flags, data, syn) {
    this.seq = (this.seq + 1) & 255;
    const sh = new Uint8Array(8); put32(sh, 0, (flags << 24) | (this.seq << 8)); put32(sh, 4, 0x200);
    const body = [...(syn ? [0, 0, 0, 2] : []), ...sh, ...(data || [])];
    const h = new Uint8Array(8); put32(h, 0, ((syn ? 2 : 1) << 28) | (2 << 26) | body.length); put32(h, 4, 0x03EF | (0x1001 << 16));
    const msg = [...h, ...body]; while (msg.length % 4) msg.push(0);
    this.q.push(new Uint8Array(msg));
    if (this.wait) { const w = this.wait; this.wait = null; w(); }
  }
  async transferIn() {
    while (!this.q.length) {
      if (this.gone) throw new Error("disconnected");
      await new Promise((r) => { this.wait = r; setTimeout(r, 50); });
    }
    const b = this.q.shift();
    return { status: "ok", data: new DataView(b.buffer) };
  }
  async transferOut(ep, data) {
    const b = Uint8Array.from(data);
    check(b.length % 4 === 0, "OUT not padded to 4");
    const w0 = u32(b, 0), w1 = u32(b, 4), type = w0 >>> 28, len = w0 & 0xFFFF;
    check(((w0 >>> 26) & 3) === 2, "transport version");
    check((w1 & 0xFFFF) === 0x1001 && (w1 >>> 16) === 0x3EF, "addresses");
    let p = 8;
    if (type === 2) { check((u32(b, 8) >>> 16) === 512, "SYN mtu"); p = 12; }
    const s0 = u32(b, p), flags = s0 >>> 24, seq = (s0 >>> 8) & 255, data2 = Array.from(b.slice(p + 8, 8 + len));
    check(seq === ((this.hostSeq + 1) & 255), "host sequence " + seq);
    this.hostSeq = seq;
    if (flags & 0x01) { check(flags === 0x21, "SYN flags"); this.queue(0x01, null, true); return { status: "ok", bytesWritten: b.length }; }
    if (!(flags & 0x04)) return { status: "ok", bytesWritten: b.length };
    this.rx.push(...data2);
    for (;;) {
      if (this.stage === 0 && this.rx.length >= 9) {
        check(this.rx.slice(0, 9).join() === [0, 0, 3, 0, 1, 0, 0, 0, 3].join(), "select service 3");
        this.rx.splice(0, 9); this.stage = 1;
      } else if (this.stage === 1 && this.rx.length >= 10) {
        this.rx.splice(0, 10); this.stage = 2; this.queue(0x04, [0, 0, 3, 0, 2, 0, 0, 0, 0, 0]);
      } else if (this.stage === 2 && this.rx.length >= 4) {
        const cmd = this.rx.splice(0, 4);
        check(cmd[0] === 0xAA, "command marker");
        if (cmd[3] === 1) this.queue(0x04, [1, 4, 4, 4]);
        else if (cmd[3] === 3) this.queue(0x04, new Array(36).fill(0));
        else if (cmd[3] === 2) {
          this.queue(0x04, [0, 0, 0, 0]);
          setTimeout(() => { usb.unplug(this); usb.plug(new Dfu(), scenario === "dfu-allowed"); }, 30);
        }
      } else break;
    }
    return { status: "ok", bytesWritten: b.length };
  }
}

// ---- the boot ROM's DFU loader
class Dfu extends Dev {
  constructor() { super(0x1FC9, 0x000C, { interfaceClass: 0xFE, interfaceSubclass: 1, endpoints: [] }); this.state = 2; this.blocks = []; }
  async controlTransferIn(s, n) {
    if (this.gone) throw new Error("gone");
    if (s.requestType === "standard" && s.request === 6) {
      const c = [9, 2, 27, 0, 1, 1, 0, 0x80, 50, 9, 4, 0, 0, 0, 0xFE, 1, 2, 0, 9, 0x21, 0x0B, 0xFF, 0, 0x00, 0x08, 0x10, 0x01];
      return { status: "ok", data: new DataView(new Uint8Array(c).buffer) };
    }
    check(s.requestType === "class" && s.recipient === "interface" && s.request === 3 && n === 6, "GETSTATUS form");
    const st = this.state;
    if (this.state === 4) this.state = 5;    // dfuDNBUSY -> dfuDNLOAD-IDLE
    return { status: "ok", data: new DataView(new Uint8Array([0, 5, 0, 0, st, 0]).buffer) };
  }
  async controlTransferOut(s, data) {
    if (this.gone) throw new Error("gone");
    check(s.requestType === "class" && s.recipient === "interface" && s.request === 1, "DNLOAD form");
    check(s.value === this.blocks.length, "block number");
    if (!data.length) {
      report.dfu = Array.from(Buffer.concat(this.blocks.map((b) => Buffer.from(b))));
      report.dfuBlocks = this.blocks.map((b) => b.length);
      setTimeout(() => { usb.unplug(this); usb.plug(new Loader(), scenario === "dfu-allowed"); }, 20);
      return { status: "ok" };
    }
    this.blocks.push(Uint8Array.from(data));
    this.state = 4;
    return { status: "ok", bytesWritten: data.length };
  }
}

// ---- the RAM loader
const emmcSector = (s) => { const b = new Uint8Array(512); b.fill(s & 255); return b; };
class Loader extends Dev {
  constructor() { super(0x1209, 0x0001, { interfaceClass: 0xFF, endpoints: [] }); this.mem = new Map(); this.ptr = 0; this.len = 0; }
  byte(a) { const pg = this.mem.get(a >>> 12); return pg ? pg[a & 4095] : 0; }
  async controlTransferIn(s, n) {
    if (this.gone) throw new Error("gone");
    check(s.requestType === "vendor" && s.recipient === "device", "vendor request form");
    const RB = RAMRUN.RB, out = new Uint8Array(n);
    if (s.request === RB.REQ_INFO) {
      out.set([82, 65, 77, 66]);
      [1, scenario === "emmc-bad" ? 3 : 1, 204, 102, 0x10b, 0x1d5a000, 0, RB.HOOK_BASE, RB.STAGE_BASE, RB.DESC, RB.FREE_END, RB.CHUNK]
        .forEach((v, i) => put32(out, 4 + 4 * i, v));
    } else if (s.request === RB.REQ_CRC) {
      const b = new Uint8Array(this.len);
      for (let i = 0; i < this.len; i++) b[i] = this.byte(this.ptr + i);
      put32(out, 0, RAMRUN.crc32(b));
    } else if (s.request === RB.REQ_EMMC_CRC) {
      const first = s.value | (s.index << 16), parts = [];
      for (let i = 0; i < this.len; i++) parts.push(emmcSector(first + i));
      put32(out, 0, RAMRUN.crc32(Buffer.concat(parts.map((p) => Buffer.from(p)))));
    } else check(false, "unknown IN request " + s.request);
    return { status: "ok", data: new DataView(out.buffer) };
  }
  async controlTransferOut(s, data) {
    if (this.gone) throw new Error("gone");
    const RB = RAMRUN.RB, arg = (s.value | (s.index << 16)) >>> 0;
    if (s.request === RB.REQ_ADDR) this.ptr = arg;
    else if (s.request === RB.REQ_LEN) this.len = arg;
    else if (s.request === RB.REQ_DATA) {
      check(data.length <= RB.CHUNK, "chunk size");
      for (let i = 0; i < data.length; i++) {
        const a = this.ptr + i;
        if (!this.mem.has(a >>> 12)) this.mem.set(a >>> 12, new Uint8Array(4096));
        this.mem.get(a >>> 12)[a & 4095] = data[i];
      }
      this.ptr += data.length;
      report.loaderWrites++;
    } else if (s.request === RB.REQ_GO) {
      check(s.value === RB.GO_KEY, "GO key");
      report.go = true;
      report.memOk = plan.regions.every((r) => r.bytes.every((x, i) => this.byte(r.addr + i) === x));
      setTimeout(() => usb.unplug(this), 20);
    } else check(false, "unknown OUT request " + s.request);
    return { status: "ok" };
  }
}

// a plan like hxf_ram.py's: an SRAM segment staged, an SDRAM segment, the hook region, the descriptor
function region(addr, n, seed) { const b = new Uint8Array(n); for (let i = 0; i < n; i++) b[i] = (i * 31 + seed) & 255; return { addr, label: "r" + seed, bytes: b }; }
const plan = {
  regions: [region(0x29E00000, 0x3491, 1), region(0x28D8FA80, 3 * 4096 + 100, 2), region(0x29000000, 9000, 3), region(0x29EFF000, 40, 4)],
  checks: [[0x8803, 3, RAMRUN.crc32(Buffer.concat([0x8803, 0x8804, 0x8805].map((s) => Buffer.from(emmcSector(s))))), 2],
           [0x8c04, 2, scenario === "emmc-bad" ? 1234 : RAMRUN.crc32(Buffer.concat([0x8c04, 0x8c05].map((s) => Buffer.from(emmcSector(s))))), 3]],
};
const image = new Uint8Array(4112); for (let i = 0; i < image.length; i++) image[i] = (i * 7) & 255;

const start = scenario === "from-dfu" ? new Dfu() : new Line6(scenario === "busy");
usb.plug(start, false);

RAMRUN.run({
  usb, plan, loader: image,
  sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
  ask: (s) => { report.ask.push(s); return scenario === "dfu-allowed" ? new Promise(() => {}) : new Promise((r) => setTimeout(r, 100)); },
  unask: () => report.ask.push("unask"),
  stage: (s) => report.stages.push(s),
}).then(() => {
  report.ok = true;
  report.dfuOk = report.dfu !== null && report.dfu.length === image.length && report.dfu.every((x, i) => x === image[i]);
  delete report.dfu;
  console.log(JSON.stringify(report));
}, (e) => {
  report.ok = false; report.code = e.code; report.message = e.message;
  delete report.dfu;
  console.log(JSON.stringify(report));
});
