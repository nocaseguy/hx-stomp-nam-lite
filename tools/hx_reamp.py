"""hx_reamp.py IMAGE|--no-ramrun CASE... : reamp the HX Stomp over USB.
Each CASE 'pid:model,pid:model,...' (path A, in order) or 'dry';
the input block set to USB 5/6 (the input block's key 5: 6 on the Stomp, whose inputs are Main L/R,
Return L/R and USB 5/6; 1 is Main L/R), build/play_mac (tools/mac/play_mac.swift) plucks on USB 5/6,
the output (USB 1/2) recorded with build/record_mac and measured as hx_smoke does. The same signal every
time, unlike hx_smoke's open input (a guitar at volume 0 is almost silence).
'dry' = a gain block only."""
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hx_smoke as hs
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
a = sys.argv[1:]
if a[0] != "--no-ramrun":
    up, l6ia = hs.ramrun(os.path.abspath(a[0]), hs.STOCK)
else:
    l6ia, _ = hs.patch_amp.load_l6ia_from_any(os.path.join(ROOT, "build/HX_Stomp_v3.80.0_HXtra.hxf"))
hs.set_profile(l6ia)

def usb_input():
    j = tempfile.mktemp(suffix=".json")
    hs.run("tools/hx_ctl.py", "--timeout", "5", "get-preset", "-o", j)
    d = json.load(open(j)); d["preset"]["0"]["22"][0]["20"]["5"] = 6
    json.dump(d, open(j, "w"))
    r = hs.run("tools/hx_ctl.py", "--timeout", "10", "load-preset", j)
    return "verified" in r.stdout

def measure(secs=4):
    wav = tempfile.mktemp(suffix=".wav")
    play = subprocess.Popen([os.path.join(ROOT, "build/play_mac"), "HX Stomp", str(secs + 2), "5,6"], stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    subprocess.run([hs.RECORDER, "HX Stomp", str(secs), wav], capture_output=True, timeout=secs + 30)
    play.wait()
    res = hs.scan(wav); os.remove(wav)
    return res

for case in a[1:]:
    if case == "dry":
        ok = hs.run("tools/hx_ctl.py", "--timeout", "8", "set-model", "--slot", "0", "--model-id", "260",
                    "--clear-after", "--clear-path-b").returncode == 0                      # a volume block only
    else:
        pids, models = zip(*[(int(x.split(":")[0]), int(x.split(":")[1])) for x in case.split(",")])
        ok = hs.place(list(pids), model=list(models))
    ok = ok and usb_input()
    db, pk, r, z, c = measure() if ok else (None,) * 5
    print(f"{hs.NAM['name']:8} {case:28} placed+usb {ok}: " + (f"{db:.1f} dBFS, peak {pk:.3f}; rep {r}, drop {z}, click {c}" if ok else "-"), flush=True)
