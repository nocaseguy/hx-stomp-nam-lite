"""Test A pass 2: per preset i: select i, 2 s; T1 = NAM, NAM, stock EQ (135), NAM on path A, input USB 5/6
(nothing playing), default knobs: record 3 s; T2 = the same with the three NAMs' tone knobs moved
(NAM reads its DDR2 tone table): record 3 s. Each must match its fresh-boot baseline constant.
usage: preset_sweep2.py IMAGE OUT.jsonl fwd|rev"""
import json, os, sys, time, statistics, math, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
image, out, order = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
sys.path.insert(0, os.path.join(ROOT, "tools")); os.chdir(ROOT)
import hx_smoke as hs
N, PER_BOOT = 126, 7
idx = list(range(N)) if order == "fwd" else list(range(N - 1, -1, -1))
idx = idx[int(os.environ.get("START", "0")):][:int(os.environ.get("LIMIT", "999"))]
D = os.path.dirname(os.path.abspath(out))
T = {k: os.path.join(D, f"tmpl2_{k}.json") for k in ("T1", "T2")}
CHAIN = [555, 555, 135, 555]
MOVED = "0.5,0.8,0.5,{pol},0.3,0.7,{m},1200.0,1,0.6"      # Input, Treble, Output, Polarity, Bass, Mid, Model, Mid Freq, Q, High Cut

def ctl(*a, t=8):
    return hs.run("tools/hx_ctl.py", "--timeout", str(t), *a)

def wait_unlocked():
    while b"<true/>" in subprocess.run("ioreg -n Root -d1 -a | grep -A1 IOConsoleLocked", shell=True, capture_output=True).stdout:
        time.sleep(20)

def boot():
    ok, l6ia = hs.ramrun(os.path.abspath(image), hs.STOCK)
    if not ok: sys.exit("ramrun failed / unit not alive")
    hs.set_profile(l6ia)
    assert hs.NAM["name"] == "donor_eq", hs.NAM

def make(key, values=None):
    orig = hs.nam_values
    if values:
        hs.nam_values = lambda model, polarity=False: values.format(pol=1 if polarity in (True, "True") else 0, m=float(model))
    try:
        assert hs.place(CHAIN, model=[4] * len(CHAIN)), f"{key}: placement failed"
    finally:
        hs.nam_values = orig
    ctl("get-preset", "-o", T[key])
    d = json.load(open(T[key])); d["preset"]["0"]["22"][0]["20"]["5"] = 6
    json.dump(d, open(T[key], "w"))

def stats():
    wait_unlocked()
    p = hs.record(3)
    x, _ = hs.read_wav(p); os.remove(p)
    x = x[4800:]
    m = statistics.fmean(x)
    return dict(mean=m, sd=statistics.pstdev(x), peak=max(abs(v - m) for v in x),
                rms_db=20 * math.log10(math.sqrt(statistics.fmean(v * v for v in x)) + 1e-12))

def take(key):
    r = ctl("load-preset", T[key], t=10)
    if "verified" not in r.stdout: return dict(loaded=False)
    time.sleep(1.5)
    return dict(loaded=True, **stats())

f = open(out, "a")
def emit(row):
    print(json.dumps(row), flush=True); f.write(json.dumps(row) + "\n"); f.flush()

boot()
if not all(os.path.exists(p) for p in T.values()):
    make("T1"); boot(); make("T2", MOVED); boot()
names = {}
for line in ctl("presets").stdout.splitlines():
    p = line.split(None, 1)
    if p and p[0].isdigit(): names[int(p[0])] = p[1] if len(p) > 1 else ""
for j, i in enumerate(idx):
    if j % PER_BOOT == 0:
        if j: boot()
        emit(dict(preset=-1, name="baseline", T1=take("T1"), T2=take("T2")))
    ctl("select", str(i)); time.sleep(2.0)
    row = dict(preset=i, name=names.get(i), T1=take("T1"), T2=take("T2"))
    row["alive"] = any(ctl("status", t=8).returncode == 0 or time.sleep(5) for _ in range(3))
    emit(row)
    if not row["alive"]: sys.exit(f"unit not answering after preset {i}")
