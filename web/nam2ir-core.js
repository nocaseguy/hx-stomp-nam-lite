// nam2ir-core.js - a NAM A2 Lite capture (.nam) as an HX Stomp User IR (.wav),
// the same bytes as tools/nam2ir.py. Runs in the browser (window.NAM2IR) and
// in Node (module.exports) for the check against the Python tool.
//
// The .wav is 2,048 samples, 48 kHz, mono, 32-bit float: a header (0.5, -0.5,
// 3.0, a scale 2^e, 1871 / 1024, the input level, the loudness, 0), then the capture's 1,871 weights
// in the order the kernel loads them, then their silence state (72 words), all
// divided by 2^e so that every sample is within HX Edit's +-15.8 limit, then zeros.
(function (root) {
  "use strict";

  var C = 3;
  var HEAD_TAPS = 16;
  var IR_SAMPLES = 2048;
  var IR_LIMIT = 15.8489;           // HX Edit refuses a sample beyond +-24 dB
  var KERNEL = [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 15, 15, 6, 6, 6, 6, 6, 6, 6];
  var DILATION = [1, 3, 7, 17, 41, 101, 239, 1, 3, 7, 17, 41, 101, 239, 1, 13, 1, 3, 7, 17, 41, 101, 239];
  var N_WEIGHTS = 1871;
  var STOMP_DBU = 11.5;             // the Stomp's input at 0 dBFS, the firmware's: tools/sharc/nam_lite.py
  var LOUD_REF = -18;               // IR word 6's reference and the firmware's target: tools/sharc/nam_lite.py
  var LOUD_TARGET = -18;            // (the NAM plugin's Normalized level)

  function same(a, b) {
    return Array.isArray(a) && a.length === b.length && a.every(function (x, i) { return x === b[i]; });
  }

  // The 3-channel WaveNet in a parsed .nam: the file itself, or the matching
  // submodel of a SlimmableContainer. Throws an Error that says what is wrong.
  function pickModel(d) {
    if (!d || typeof d !== "object" || !d.architecture) {
      throw new Error("This is not a NAM model file: it has no architecture.");
    }
    var subs = d.architecture === "SlimmableContainer"
      ? ((d.config && d.config.submodels) || []).map(function (s) { return s.model; })
      : [d];
    var seen = [];
    for (var i = 0; i < subs.length; i++) {
      var m = subs[i];
      if (!m || m.architecture !== "WaveNet" || !m.config || !m.config.layers || !m.config.layers.length) {
        if (m && m.architecture) seen.push(m.architecture);
        continue;
      }
      var ch = m.config.layers[0].channels;
      if (ch === C) return { model: m, slimmable: d.architecture === "SlimmableContainer" };
      seen.push(ch + "-channel WaveNet");
    }
    throw new Error("No 3-channel A2 Lite model inside (found: " + (seen.join(", ") || "nothing usable") +
                    "). NAM A2 Lite plays A2 Lite captures only.");
  }

  // What would make the kernel compute something else than this capture: the A2 shape,
  // tools/sharc/nam_pack.py a2_mismatch() (NeuralAmpModelerCore's is_a2_shape, rule for rule).
  function problems(m) {
    var out = [];
    var cfg = m.config;
    var L = cfg.layers;
    if (L.length !== 1) out.push(L.length + " layer arrays; A2 Lite has 1");
    var l = L[0];
    var off = function (v) { return v === undefined || v === null || v === false || (typeof v === "object" && !v.active); };
    if (!(cfg.head === undefined || cfg.head === null) || !(cfg.condition_dsp === undefined || cfg.condition_dsp === null)) {
      out.push("a post-stack head or a condition DSP");
    }
    if (typeof cfg.head_scale !== "number" || (cfg.in_channels !== undefined && cfg.in_channels !== 1)) out.push("no head_scale");
    if (l.input_size !== 1 || l.condition_size !== 1) out.push("input_size and condition_size are not 1");
    if (l.bottleneck !== C) out.push("bottleneck is not " + C);
    if (!l.kernel_sizes || !l.dilations) out.push("no kernel sizes or dilations");
    if (!Array.isArray(l.activation) || l.activation.length !== KERNEL.length) out.push("not one activation per layer");
    if (l.gated === true) out.push("gated");
    if (l.secondary_activation !== undefined && l.secondary_activation !== null &&
        !(Array.isArray(l.secondary_activation) && l.secondary_activation.length === KERNEL.length &&
          l.secondary_activation.every(function (x) { return x === null; }))) out.push("a secondary activation");
    if (l.head1x1 && typeof l.head1x1 === "object" && l.head1x1.active) out.push("head1x1 is on");
    if (!l.layer1x1 || !l.layer1x1.active || (l.layer1x1.groups !== undefined && l.layer1x1.groups !== 1)) out.push("layer1x1 is not on with groups 1");
    var h = l.head;
    if (!h || h.out_channels !== 1 || h.kernel_size !== HEAD_TAPS || (h.head_dilation !== undefined && h.head_dilation !== 1) || !h.bias) {
      out.push("the head is not " + HEAD_TAPS + " taps with a bias");
    }
    ["conv_pre_film", "conv_post_film", "input_mixin_pre_film", "input_mixin_post_film", "activation_pre_film",
     "activation_post_film", "layer1x1_post_film", "head1x1_post_film"].forEach(function (k) {
      if (!off(l[k])) out.push("FiLM (" + k + ")");
    });
    if ((l.groups_input !== undefined && l.groups_input !== 1) || (l.groups_input_mixin !== undefined && l.groups_input_mixin !== 1)) {
      out.push("grouped convolutions");
    }
    if (l.slimmable !== undefined && l.slimmable !== null) out.push("slimmable layers");
    if (l.kernel_sizes && !same(l.kernel_sizes, KERNEL)) out.push("kernel sizes differ from A2's");
    if (l.dilations && !same(l.dilations, DILATION)) out.push("dilations differ from A2's");
    (l.activation || []).forEach(function (a, i) {
      if (!a || typeof a !== "object" || a.type !== "LeakyReLU" || !(Math.abs((a.negative_slope || 0) - 0.01) <= 1e-7)) {
        out.push("layer " + (i + 1) + " uses " + (a && a.type) + "; the kernel has LeakyReLU 0.01");
      }
    });
    (l.gating_mode || []).forEach(function (g, i) {
      if (g !== "none") out.push("layer " + (i + 1) + " is gated");
    });
    if (l.gating_mode !== undefined && l.gating_mode !== null &&
        !(Array.isArray(l.gating_mode) && l.gating_mode.length === KERNEL.length)) out.push("not one gating mode per layer");
    if (!Array.isArray(m.weights) || m.weights.length !== N_WEIGHTS) {
      out.push((m.weights ? m.weights.length : 0) + " weights; A2 Lite has " + N_WEIGHTS);
    }
    return out;
  }

  // The capture's input level in dBu (metadata input_level_dbu), or null when
  // the file does not give a number: tools/sharc/nam_pack.py input_level_dbu().
  function inputLevelDbu(meta) {
    var dbu = meta && meta.input_level_dbu;
    return typeof dbu === "number" && isFinite(dbu) ? dbu : null;
  }

  // The capture's loudness in dB (metadata loudness), or null: nam_pack.py loudness().
  function loudness(meta) {
    var x = meta && meta.loudness;
    return typeof x === "number" && isFinite(x) ? x : null;
  }

  // IR word 6: tools/sharc/nam_lite.py loud_word(); 0 (left as it is) when too quiet.
  function loudWord(db) {
    if (db === null) return 0;
    var g = Math.fround(Math.pow(10, (LOUD_REF - db) / 20));
    return g > 0 && g < IR_LIMIT ? g : 0;
  }

  // IR word 5: tools/sharc/nam_lite.py level_word().
  function levelWord(dbu) {
    if (dbu === null) return 0;
    var g = Math.fround(Math.pow(10, -dbu / 20));
    if (!(g > 0 && g < IR_LIMIT)) throw new Error("Input level " + dbu + " dBu is out of range (above -24 dBu).");
    return g;
  }

  // tools/sharc/nam_lite.py layer_weights(): per layer bias and mix-in per
  // output channel, the taps [tap][input][output], then per output channel
  // bias1 and its 1x1 weights; the head (bias, then [tap][channel]); the
  // rechannel weights; the head scale.
  function layerWeights(w) {
    var o = C, blocks = [];
    KERNEL.forEach(function (k) {
      var conv = o; o += C * C * k;
      var bias = o; o += C;
      var mixin = o; o += C;
      var w1 = o; o += C * C;
      var b1 = o; o += C;
      var blk = [], i, j, t;
      for (i = 0; i < C; i++) blk.push(w[bias + i], w[mixin + i]);
      for (t = 0; t < k; t++) for (j = 0; j < C; j++) for (i = 0; i < C; i++) blk.push(w[conv + (i * C + j) * k + t]);
      for (i = 0; i < C; i++) {
        blk.push(w[b1 + i]);
        for (j = 0; j < C; j++) blk.push(w[w1 + i * C + j]);
      }
      blocks.push(blk);
    });
    var head = [w[o + C * HEAD_TAPS]];
    for (var t = 0; t < HEAD_TAPS; t++) for (var j = 0; j < C; j++) head.push(w[o + j * HEAD_TAPS + t]);
    return { blocks: blocks, head: head, rech: w.slice(0, C), scale: w[o + C * HEAD_TAPS + 1] };
  }

  // tools/sharc/nam_lite.py silence(): what the rings hold after silence, in
  // float32 op for op as the kernel adds: the head's input (3) and each layer's
  // input x (23 x 3). A change of model fills the rings with it, so it does not pop.
  function silence(w) {
    var f = Math.fround;
    var lw = layerWeights(w.map(f));
    var x = lw.rech.map(function (r) { return f(r * 0); });
    var hs = [0, 0, 0], xs = [];
    KERNEL.forEach(function (k, n) {
      var blk = lw.blocks[n], a = [], i, j, t;
      xs.push(x.slice());
      for (i = 0; i < C; i++) {
        var v = f(f(blk[2 * i] + f(blk[2 * i + 1] * 0)) + 0);
        for (t = 0; t < k; t++) for (j = 0; j < C; j++) v = f(v + f(blk[2 * C + (t * C + j) * C + i] * x[j]));
        a.push(Math.max(v, f(v * f(0.01))));
      }
      hs = hs.map(function (h, i) { return f(h + a[i]); });
      var o = 2 * C + k * C * C;
      for (i = 0; i < C; i++) {
        var u = blk[o + 4 * i];
        for (j = 0; j < C; j++) u = f(u + f(a[j] * blk[o + 4 * i + 1 + j]));
        x[i] = f(x[i] + u);
      }
    });
    return { hs: hs, xs: xs };
  }

  // The words a model loads as: the 1,871 weights, then its silence state
  // (72 words, each / 16, as the kernel keeps them).
  function stream(w) {
    var lw = layerWeights(w);
    var out = lw.rech.concat(lw.head, [lw.scale]);
    lw.blocks.forEach(function (b) { out = out.concat(b); });
    var s = silence(w);
    s.xs.forEach(function (x) { s.hs = s.hs.concat(x); });
    return out.concat(s.hs.map(function (v) { return v / 16; }));
  }

  // The 2,048 IR samples as a Float32Array, and the scale exponent.
  function irSamples(w, dbu, loud) {
    var st = stream(w);
    var peak = 0;
    st.forEach(function (x) { peak = Math.max(peak, Math.abs(x)); });
    var e = 0;
    while (peak / Math.pow(2, e) > 15.5) e++;
    var s = Math.pow(2, e);
    var vals = [0.5, -0.5, C, s, N_WEIGHTS / 1024, levelWord(dbu === undefined ? null : dbu),
                loudWord(loud === undefined ? null : loud), 0].concat(st.map(function (x) { return x / s; }));
    if (vals.length >= IR_SAMPLES) throw new Error("Too many weights for one IR slot.");
    vals.forEach(function (v) {
      if (!(Math.abs(v) < IR_LIMIT)) throw new Error("A sample HX Edit would refuse (" + v + ").");
    });
    var out = new Float32Array(IR_SAMPLES);
    out.set(vals);
    return { samples: out, exponent: e, peak: peak };
  }

  // A 48 kHz mono IEEE-float .wav, as tools/nam2ir.py write_wav().
  function wavBytes(samples) {
    var n = samples.length, buf = new ArrayBuffer(44 + 4 * n), v = new DataView(buf);
    function tag(o, s) { for (var i = 0; i < 4; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    tag(0, "RIFF"); v.setUint32(4, 36 + 4 * n, true); tag(8, "WAVE");
    tag(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 3, true); v.setUint16(22, 1, true);
    v.setUint32(24, 48000, true); v.setUint32(28, 48000 * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 32, true);
    tag(36, "data"); v.setUint32(40, 4 * n, true);
    for (var i = 0; i < n; i++) v.setFloat32(44 + 4 * i, samples[i], true);
    return new Uint8Array(buf);
  }

  // "Mesa Boogie" + "Mesa Boogie JP-2C" -> "Mesa Boogie JP-2C"; unset fields left out.
  function gearName(make, model) {
    var ok = function (x) { return typeof x === "string" && x && x !== "t3k-unset"; };
    if (!ok(make)) return ok(model) ? model : "";
    if (!ok(model)) return make;
    return model.toLowerCase().indexOf(make.toLowerCase()) === 0 ? model : make + " " + model;
  }

  // Text of a .nam file -> { wav, info } or an Error thrown. opts: level: false
  // to leave the input level out (word 5 0: no trim); loudness: false to leave the
  // loudness out (word 6 0: as it comes out).
  function convert(text, opts) {
    opts = opts || {};
    var d;
    try { d = JSON.parse(text); } catch (err) { throw new Error("The file is not valid JSON, so not a .nam file."); }
    var pick = pickModel(d);
    var bad = problems(pick.model);
    if (bad.length) throw new Error("Not an A2 Lite capture the kernel can run: " + bad.join("; ") + ".");
    var meta = d.metadata || {};
    [d.sample_rate, pick.model.sample_rate].forEach(function (rate) {
      if (rate !== undefined && rate !== null && rate !== 48000) {
        throw new Error("Trained at " + rate + " Hz; the Stomp runs at 48 kHz and does not resample, so it would sound off.");
      }
    });
    var dbu = opts.level === false ? null : inputLevelDbu(meta);
    var loud = opts.loudness === false ? null : loudness(meta);
    var ir = irSamples(pick.model.weights, dbu, loud);
    var rate = pick.model.sample_rate || d.sample_rate;
    return {
      wav: wavBytes(ir.samples),
      info: {
        name: meta.name || "",
        modeledBy: meta.modeled_by || "",
        gear: gearName(meta.gear_make, meta.gear_model),
        slimmable: pick.slimmable,
        exponent: ir.exponent,
        peak: ir.peak,
        inputDbu: dbu,
        trimDb: dbu === null ? null : STOMP_DBU - dbu,
        loudness: loud,
        loudDb: loud === null || !loudWord(loud) ? null : LOUD_TARGET - loud,
        sampleRate: rate,
        warnings: []
      }
    };
  }

  var api = { STOMP_DBU: STOMP_DBU, LOUD_TARGET: LOUD_TARGET, convert: convert, pickModel: pickModel, problems: problems, irSamples: irSamples, wavBytes: wavBytes };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.NAM2IR = api;
})(this);
