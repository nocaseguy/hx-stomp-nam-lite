// firmware-worker.js - build.py in the browser: the stock .hxf in, the HXtra
// .hxf out, with NAM A2 Lite and, on the HX Stomp, the release's HXtra
// features. Pyodide runs the repository's own Python tools, the same
// commands build.py runs (without --check, the simulator run, which takes
// minutes here). The features' M4 code comes from the release's m4cache.json
// (tools/m4cache.py), next to the page, since there is no clang here. The
// result's MD5 is then compared with the pinned build: tests/test_firmware.py's
// with no features, the release's with them. A match means the
// bytes are the very file that build makes on a desktop.
//
// Messages in:  { stock: ArrayBuffer, features: ["HX_BPM", ...] }
// It also lays out the RAM run of the result (tools/hxf_ram.py plan), for
// ramrun.js: the regions to send and the eMMC checks.
//
// Messages out: { type: "progress", step, of, text } | { type: "log", text }
//               { type: "done", unit, file, bytes: ArrayBuffer, md5, pinned (true, false, or null: no pinned build),
//                 ram: { regions: [{ addr, label, bytes: ArrayBuffer }], checks } | { error } }
//               { type: "error", text }
"use strict";

var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

// tests/test_web_build.py keeps these equal to build.py's STOCK_MD5 and
// tests/test_firmware.py's BUILT_MD5.
var STOCK_MD5 = {
  "a2cd8f4ae56f49415380270ebc484bf1": "HX_Stomp",
  "329e3a26d60d3de1988b6785fa833ee1": "HX_Stomp_XL",
  "7c2ebdf1bffb6bcc5f89dda97f91e40c": "HX_Effects",
};
var BUILT_MD5 = {
  "HX_Stomp": "8673ca7e83ec469e2ea79348eea99ca6",
  "HX_Stomp_XL": "8918ab60ebff62ebfccd4fccb2bed85a",
  "HX_Effects": "2efb98791581b67116ba82c5ecd30ea2",
};

// build.py's KERNEL and STEPS (tests/test_web_build.py keeps them equal): per unit, the kernel
// command and the patch_amp.py steps, each "patch_amp.py CMD IN OUT ARGS..." on the previous output.
// GR_SLOTS too: build.py's kernel(unit) adds it on an HX Stomp build with the GR meter.
var GR_SLOTS = ["--slots", "2"];
var KERNEL = {"HX_Stomp": ["tools/sharc/nam_multi.py", "--mid-sweep"], "HX_Stomp_XL": ["tools/sharc/nam_multi.py", "--mid-sweep"], "HX_Effects": ["tools/sharc/nam_multi.py", "--mid-sweep", "--effects"]};
var STEPS = {
  "HX_Stomp": [
    ["remove-model", "--preset-id", "555"],
    ["add-fx-model", "--knobs", "eq", "--name", "HD2_DistNAMLite", "--display-name", "NAM A2 Lite", "--category", "distortion", "--folder", "NAM", "--preset-id", "555", "--dsp-cost", "2275", "--sdram-words", "0x5000", "--dm-words", "0x303", "--pm-words", "0x147"],
    ["move-folder", "--name", "NAM", "--from", "2", "--to", "12"],
    ["ir-title", "--fx-preset-id", "555", "--knob", "6"],
  ],
  "HX_Stomp_XL": [
    ["remove-model", "--preset-id", "555"],
    ["add-fx-model", "--knobs", "eq", "--name", "HD2_DistNAMLite", "--display-name", "NAM A2 Lite", "--category", "distortion", "--folder", "NAM", "--preset-id", "555", "--dsp-cost", "2275", "--sdram-words", "0x5000", "--dm-words", "0x303", "--pm-words", "0x147"],
    ["move-folder", "--name", "NAM", "--from", "2", "--to", "12"],
    ["ir-title", "--fx-preset-id", "555", "--knob", "6"],
  ],
  "HX_Effects": [
    ["effects-eq"],
  ],
};

// What build.py needs, relative to the repository root.
var SOURCES = [
  "build.py",
  "tools/hxf.py",
  "tools/l6ia.py",
  "tools/hxf_ram.py",
  "tools/l6ia_verify.py",
  "tools/patch_amp.py",
  "tools/effects.py",
  "tools/patch_menu.py",
  "tools/patch_click.py",
  "tools/patch_comp.py",
  "tools/m4asm.py",
  "tools/image_store.py",
  "tools/patch_splash.py",
  "tools/splash_emoji.py",
  "tools/splash_hxtra.py",
  "tools/setting_ids.py",
  "tools/features/__init__.py",
  "tools/features/bpm.py",
  "tools/features/breathing_line.py",
  "tools/features/dsp_meter.py",
  "tools/features/gr.py",
  "tools/features/long_press.py",
  "tools/features/metronome.py",
  "tools/features/more_snapshots.py",
  "tools/features/splash.py",
  "tools/features/tuner.py",
  "tools/kit_patch_amp.py",
  "tools/sharc/entry4_blob.py",
  "tools/sharc/nam_lite.py",
  "tools/sharc/nam_multi.py",
  "tools/sharc/nam_multi_kernel.asm",
  "tools/sharc/nam_pack.py",
  "tools/sharc/recips_table.json",
  "tools/sharc/sasm.py",
  "tools/sharc/ssim.py",
  "tools/ramboot/ramboot-hook.bin",
  "src/m4/bpm.s",
  "src/m4/breathing_line.s",
  "src/m4/dsp_meter.s",
  "src/m4/gr_meter.s",
  "src/m4/long_press.s",
  "src/m4/metronome.s",
  "src/m4/more_snapshots.s",
  "src/m4/strip.s",
  "src/m4/tuner.s",
  "src/m4/virtual_settings.s",
  "src/sharc/click.asm",
  "src/sharc/frame_probe.asm",
];
// The release's M4 code for the features (tools/m4cache.py); a page from a checkout has none, and offers no features.
var CACHE = "m4cache.json";

// One command of build.py: run a script as __main__ with argv, return its output.
var DRIVER = [
  "import contextlib, io, os, runpy, sys",
  "os.chdir('/repo')",
  "def run(argv):",
  "    out = io.StringIO()",
  "    sys.argv = list(argv)",
  "    try:",
  "        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):",
  "            runpy.run_path(argv[0], run_name='__main__')",
  "    except SystemExit as e:",
  "        if e.code not in (None, 0):",
  "            raise RuntimeError(out.getvalue() + str(e.code))",
  "    return out.getvalue()",
].join("\n");

var py = null, cache = null;

function post(msg, transfer) { self.postMessage(msg, transfer || []); }
function progress(step, of, text) { post({ type: "progress", step: step, of: of, text: text }); }

async function boot() {
  if (py) return py;
  importScripts(PYODIDE + "pyodide.js");
  var p = await loadPyodide({ indexURL: PYODIDE });
  await p.loadPackage("numpy");
  var root = new URL("../", self.location.href).href;
  var files = await Promise.all(SOURCES.map(async function (path) {
    var r = await fetch(root + path, { cache: "no-cache" });
    if (!r.ok) throw new Error("Could not load " + path + " (" + r.status + ").");
    return [path, new Uint8Array(await r.arrayBuffer())];
  }));
  var c = await fetch(root + CACHE, { cache: "no-cache" });
  if (c.ok) cache = await c.json();
  ["/repo", "/repo/tools", "/repo/tools/features", "/repo/tools/sharc", "/repo/tools/ramboot", "/repo/src", "/repo/src/m4", "/repo/src/sharc",
   "/repo/build"].forEach(function (d) {
    try { p.FS.mkdir(d); } catch (e) { /* exists */ }
  });
  files.forEach(function (f) { p.FS.writeFile("/repo/" + f[0], f[1]); });
  if (cache) p.FS.writeFile("/repo/" + CACHE, JSON.stringify(cache));
  p.runPython(DRIVER);
  py = p;
  return p;
}

// The features' switches for patch_menu.py, as build.py's environment would have them; the M4 code from the cache.
function setFeatures(p, flags) {
  p.globals.set("flags", p.toPy(flags));
  p.runPython([
    "for k in [k for k in os.environ if k.startswith('HX_')]: del os.environ[k]",
    "os.environ.update({f: '1' for f in flags})",
    "if flags: os.environ['HX_M4_CACHE'] = '/repo/" + CACHE + "'",
  ].join("\n"));
}

async function build(stock, flags) {
  var of = 6;
  progress(1, of, "Loading the build tools (about 15 MB, once)…");
  var p = await boot();

  progress(2, of, "Checking your firmware file…");
  p.FS.writeFile("/repo/build/stock.hxf", new Uint8Array(stock));
  stock = null;
  var md5 = p.runPython("import hashlib; hashlib.md5(open('/repo/build/stock.hxf','rb').read()).hexdigest()");
  var unit = STOCK_MD5[md5];
  if (!unit) {
    throw new Error("This is not the stock HX Stomp, HX Stomp XL or HX Effects 3.80.0 firmware (its MD5 is " + md5 +
                    "). The patch is made for those three files only.");
  }
  post({ type: "log", text: "stock firmware: " + unit.replace(/_/g, " ") + " 3.80.0 (MD5 " + md5 + ")\n" });
  flags = unit === "HX_Stomp" ? (flags || []) : [];
  if (flags.length && !cache) throw new Error("This page has no feature code (" + CACHE + "): build without features.");
  flags.forEach(function (f) {
    if (cache.features.indexOf(f) < 0) throw new Error("This release has no feature " + f + ".");
  });
  setFeatures(p, flags);
  post({ type: "log", text: "features: " + (flags.join(" ") || "none") + "\n" });

  var run = p.globals.get("run");
  function step(n, text, argv) {
    progress(n, of, text);
    post({ type: "log", text: "$ " + argv.join(" ") + "\n" });
    var out = run(p.toPy(argv));
    post({ type: "log", text: out });
    return out;
  }
  try {
    var gr = flags.indexOf("HX_GR") >= 0;
    step(3, "Building the NAM kernel…", KERNEL[unit].concat(gr ? GR_SLOTS : [], ["-o", "build/nam_lite.asm"]));
    var base = "build/stock.hxf";
    STEPS[unit].forEach(function (s, k) {
      var out = "build/nam_lite_" + k + ".l6ia";
      step(4, "Adding NAM A2 Lite…", ["tools/patch_amp.py", s[0], base, out].concat(s.slice(1)));
      if (base !== "build/stock.hxf") p.FS.unlink("/repo/" + base);
      base = out;
    });
    if (unit === "HX_Stomp") {
      step(4, "Adding NAM A2 Lite…", ["tools/patch_menu.py", base, "build/nam_lite_menu.l6ia"]);
      p.FS.unlink("/repo/" + base);
      base = "build/nam_lite_menu.l6ia";
    }
    step(5, "Adding the kernel to the DSP program…",
         ["tools/patch_amp.py", "patch", base, "build/nam_lite.l6ia", "--asm", "build/nam_lite.asm"]);
    p.FS.unlink("/repo/" + base);
    if (flags.indexOf("HX_CLICK") >= 0) {
      step(5, "Adding the kernel to the DSP program…",
           ["tools/patch_click.py", "build/nam_lite.l6ia", "build/nam_lite_click.l6ia"]);
      p.FS.rename("/repo/build/nam_lite_click.l6ia", "/repo/build/nam_lite.l6ia");
    }
    if (gr) {           // last, as in build.py: every step that adds a model rebuilds the tails its knobs live in
      step(5, "Adding the kernel to the DSP program…",
           ["tools/patch_comp.py", "build/nam_lite.l6ia", "build/nam_lite_comp.l6ia"]);
      p.FS.rename("/repo/build/nam_lite_comp.l6ia", "/repo/build/nam_lite.l6ia");
    }
    var report = step(6, "Checking every checksum and packing the file…",
                      ["tools/l6ia_verify.py", "build/nam_lite.l6ia"]);
    if (report.indexOf("ALL OK") < 0) throw new Error("The built image failed its checksum check.");
    var file = unit + "_v3.80.0_HXtra.hxf";
    step(6, "Checking every checksum and packing the file…",
         ["tools/hxf.py", "pack", "build/nam_lite.l6ia", "build/" + file, "--donor", "build/stock.hxf"]);
    var ram = ramPlan(p, step, file);
  } finally {
    run.destroy();
  }
  var bytes = p.FS.readFile("/repo/build/" + file);
  var outMd5 = p.runPython("import hashlib; hashlib.md5(open('/repo/build/" + file + "','rb').read()).hexdigest()");
  ["stock.hxf", "nam_lite.l6ia", file].forEach(function (f) {
    try { p.FS.unlink("/repo/build/" + f); } catch (e) { /* gone */ }
  });
  var buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  var want = flags.length ? (cache.md5[unit] || {})[flags.slice().sort().join("+")] : BUILT_MD5[unit];
  post({ type: "done", unit: unit, file: file, bytes: buf, md5: outMd5, pinned: want ? outMd5 === want : null, ram: ram },
       [buf].concat(ram.regions ? ram.regions.map(function (r) { return r.bytes; }) : []));
}

// The RAM run of the built file: what tools/hxf_ram.py run would send. A failure here leaves the
// build as it is; the page then offers no RAM run.
function ramPlan(p, step, file) {
  if (file.indexOf("HX_Effects") === 0) {      // the RAM loader is the HX Stomp's and XL's only
    post({ type: "log", text: "RAM run: HX Stomp and HX Stomp XL only.\n" });
    return {};
  }
  var dir = "/repo/build/ram";
  try {
    step(6, "Checking every checksum and packing the file…",
         ["tools/hxf_ram.py", "plan", "build/" + file, "--stock", "build/stock.hxf", "--out", "build/ram"]);
    var meta = JSON.parse(new TextDecoder().decode(p.FS.readFile(dir + "/plan.json")));
    var regions = meta.regions.map(function (r) {
      var b = p.FS.readFile(dir + "/" + r.file);
      return { addr: r.addr, label: r.label, bytes: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) };
    });
    return { regions: regions, checks: meta.checks };
  } catch (e) {
    post({ type: "log", text: "RAM run not available: " + (e && e.message ? e.message : e) + "\n" });
    return { error: String(e && e.message ? e.message : e) };
  } finally {
    try {
      p.FS.readdir(dir).forEach(function (f) { if (f !== "." && f !== "..") p.FS.unlink(dir + "/" + f); });
      p.FS.rmdir(dir);
    } catch (e) { /* not made */ }
  }
}

self.onmessage = function (e) {
  build(e.data.stock, e.data.features).catch(function (err) {
    post({ type: "error", text: err && err.message ? err.message : String(err) });
  });
};
