import json, sys, os
d = os.getcwd()
for fn in sys.argv[1:]:
    rows = [json.loads(l) for l in open(os.path.join(d, fn))]
    B = {k: [r[k] for r in rows if r["preset"] == -1 and r[k].get("loaded")] for k in ("T1", "T2")}
    base = {k: [s["mean"] for s in v] for k, v in B.items()}
    lim = {k: (3 * max(s["sd"] for s in v), 4 * max(s["peak"] for s in v)) for k, v in B.items()}   # the baselines' own noise
    print(fn, "noise limits (sd, peak):", {k: ("%.1e" % a, "%.1e" % b) for k, (a, b) in lim.items()})
    print(fn, "baselines T1 span %.2e T2 span %.2e" % tuple(max(v) - min(v) for v in base.values()),
          "T1 %.6e T2 %.6e" % (base["T1"][0], base["T2"][0]))
    rs = [r for r in rows if r["preset"] >= 0]; bad = []
    for r in rs:
        for k in ("T1", "T2"):
            s = r[k]
            if not s.get("loaded") or s["sd"] > lim[k][0] or s["peak"] > lim[k][1] or abs(s["mean"] - base[k][0]) > 1e-8:
                bad.append((r["preset"], r.get("name"), k, s))
        if not r["alive"]: bad.append((r["preset"], r.get("name"), "alive", False))
    for k in ("T1", "T2"):
        v = [r[k] for r in rs if r[k].get("loaded")]
        print(f"  {k}: {len(v)} presets, max sd {max(s['sd'] for s in v):.2e}, max peak {max(s['peak'] for s in v):.2e}, "
              f"max |mean-base| {max(abs(s['mean'] - base[k][0]) for s in v):.2e}")
    print("  FLAGGED", len(bad)); [print("   ", b) for b in bad]
