import json, sys, glob, os
d = os.getcwd()
for fn in sys.argv[1:] or ("fwd.jsonl", "rev.jsonl"):
    p = os.path.join(d, fn)
    if not os.path.exists(p): continue
    rows = [json.loads(l) for l in open(p)]
    base = [r for r in rows if r["preset"] == -1]
    rs = [r for r in rows if r["preset"] >= 0]
    bad = [r for r in rs if not r.get("loaded") or not r.get("alive") or r.get("sd", 1) > 1e-6
           or abs(r.get("mean", 0) - base[0]["mean"]) > 1e-6 or r.get("peak", 1) > 1e-5]
    print(fn, "presets", len(rs), "unique", len({r["preset"] for r in rs}), "baselines", len(base),
          "max sd %.2e" % max(r.get("sd", 0) for r in rs), "max peak %.2e" % max(r.get("peak", 0) for r in rs),
          "mean span %.2e" % (max(r["mean"] for r in rs if "mean" in r) - min(r["mean"] for r in rs if "mean" in r)),
          "FLAGGED", len(bad))
    for r in bad: print("  ", r)
