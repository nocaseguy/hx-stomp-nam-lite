"""Test A: does any factory preset leave something that corrupts NAM's memory?
RAM-run IMAGE; template = NAM (Model 4) alone in slot 0, input block USB 5/6 with nothing
playing (digital zero). For each preset i (in ORDER): select i, wait, load the template, wait, record
3 s; NAM's output from zero input must be the same constant every time (spread ~0).
usage: preset_sweep.py IMAGE OUT.jsonl fwd|rev [start]"""
import json, os, sys, time, tempfile, statistics, math
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
image, out, order = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
sys.path.insert(0, os.path.join(ROOT, "tools")); os.chdir(ROOT)
import hx_smoke as hs
start = int(sys.argv[4]) if len(sys.argv) > 4 else 0
N, PER_BOOT = 126, 12
idx = list(range(N)) if order == "fwd" else list(range(N - 1, -1, -1))
idx = idx[start:][:int(os.environ.get("LIMIT", "999"))]
tmpl = os.path.join(os.path.dirname(out), "template.json")

def ctl(*a, t=8):
    return hs.run("tools/hx_ctl.py", "--timeout", str(t), *a)

def boot():
    ok, l6ia = hs.ramrun(os.path.abspath(image), hs.STOCK)
    if not ok:
        sys.exit("ramrun failed / unit not alive")
    hs.set_profile(l6ia)
    assert hs.NAM["name"] == os.environ.get("PROFILE", "donor_eq"), hs.NAM

def make_template():
    assert hs.place([hs.NAM["a"]], model=[4]), "NAM placement failed"
    ctl("get-preset", "-o", tmpl)
    d = json.load(open(tmpl)); d["preset"]["0"]["22"][0]["20"]["5"] = 6
    json.dump(d, open(tmpl, "w"))

def stats():
    p = hs.record(3)
    x, _ = hs.read_wav(p); os.remove(p)
    x = x[4800:]                                   # skip the first 0.1 s
    m = statistics.fmean(x)
    return dict(n=len(x), mean=m, sd=statistics.pstdev(x), peak=max(abs(v - m) for v in x),
                distinct=len(set(x)), rms_db=20 * math.log10(math.sqrt(statistics.fmean(v * v for v in x)) + 1e-12))

boot(); make_template()
r = ctl("load-preset", tmpl, t=10); assert "verified" in r.stdout, r.stdout
time.sleep(1.5)
f = open(out, "a")
f.write(json.dumps(dict(preset=-1, name="baseline (fresh boot)", **stats())) + "\n"); f.flush()
names = {}
for line in ctl("presets").stdout.splitlines():
    p = line.split(None, 1)
    if p and p[0].isdigit(): names[int(p[0])] = p[1] if len(p) > 1 else ""
done = 0
for i in idx:
    if done and done % PER_BOOT == 0:
        boot()
    s = ctl("select", str(i))
    time.sleep(2.0)                                # the preset runs (its objects live)
    r = ctl("load-preset", tmpl, t=10)
    ok = "verified" in r.stdout
    time.sleep(1.5)
    st = stats() if ok else {}
    alive = ctl("status", t=5).returncode == 0
    row = dict(preset=i, name=names.get(i), loaded=ok, alive=alive, **st)
    print(json.dumps(row), flush=True); f.write(json.dumps(row) + "\n"); f.flush()
    done += 1
    if not alive:
        sys.exit(f"unit not answering after preset {i}")
