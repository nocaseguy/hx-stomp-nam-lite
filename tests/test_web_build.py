"""web/firmware-worker.js, the in-browser build.py: it accepts the same stock files,
pins the same built MD5s, and loads every file the build reads; with HX_STOMP_HXF set, its
copy of the repository builds the features from a release's M4 code (tools/m4cache.py) as
the repository does with clang."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import m4asm
import m4cache

ROOT = Path(__file__).resolve().parent.parent
WORKER = (ROOT / "web/firmware-worker.js").read_text()


def js_object(name):
    body = re.search(name + r" = \{(.*?)\};", WORKER, re.S).group(1)
    return dict(re.findall(r'"(\w+)": "(\w+)"', body))


def py_dict(path, name):
    """A module-level value of literals, or of names of such values assigned before it."""
    tree = ast.parse((ROOT / path).read_text())
    env = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            try:
                env[n.targets[0].id] = eval(compile(ast.Expression(n.value), path, "eval"), {"__builtins__": {}}, dict(env))
            except Exception:
                continue
            if n.targets[0].id == name:
                return env[name]
    raise KeyError(name)


def test_stock_md5_as_build_py():
    assert js_object("STOCK_MD5") == py_dict("build.py", "STOCK_MD5")


def js_value(name):
    """A var whose value is a JSON string, list or object."""
    body = re.search(r"var " + name + r" = (.*?);\n", WORKER, re.S).group(1)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", body))


def test_build_steps_as_build_py():
    for name in ("KERNEL", "GR_SLOTS", "STEPS"):
        assert js_value(name) == py_dict("build.py", name), name


def test_built_md5_as_firmware_test():
    pinned = py_dict("tests/test_firmware.py", "BUILT_MD5")
    assert js_object("BUILT_MD5") == {"HX_Stomp": pinned["HX_STOMP_HXF"], "HX_Stomp_XL": pinned["HX_STOMP_XL_HXF"],
                                      "HX_Effects": pinned["HX_EFFECTS_HXF"]}


def test_sources_cover_the_build():
    listed = set(listed_sources())
    assert all((ROOT / p).is_file() for p in listed)
    # every module the build's scripts import, and every file they open next to themselves
    need = {"tools/hxf.py", "tools/l6ia.py", "tools/l6ia_verify.py", "tools/patch_amp.py", "tools/kit_patch_amp.py",
            "tools/sharc/nam_lite.py",
            "tools/sharc/nam_multi.py", "tools/sharc/nam_multi_kernel.asm",
            *(f"tools/features/{f.name}" for f in (ROOT / "tools/features").glob("*.py")),
            "tools/patch_click.py", "build.py", "src/sharc/click.asm",      # the Metronome: patch_click.py reads both
            "tools/patch_comp.py", "src/sharc/frame_probe.asm"}             # the GR meter's knobs and DSP code
    for d in ("tools", "tools/sharc"):
        for f in listed:
            if not f.endswith(".py"):
                continue
            for mod in re.findall(r"^\s*import (\w+)", (ROOT / f).read_text(), re.M):
                if (ROOT / d / f"{mod}.py").is_file():
                    need.add(f"{d}/{mod}.py")
            for name in re.findall(r"""['"](\w+\.(?:json|asm))['"]""", (ROOT / f).read_text()):
                if (ROOT / d / name).is_file() and d == str(Path(f).parent):
                    need.add(f"{d}/{name}")
    assert need - {"tools/sharc/nam_a2.asm"} <= listed


def listed_sources():
    return re.findall(r'"((?:tools/|src/)?[\w/.]+\.\w+)"', WORKER.split("var SOURCES")[1].split("];")[0])


def test_sources_have_every_m4_source():
    # m4asm.key hashes every source next to a module, so the page needs all of them, as at the release
    m4 = {f"src/m4/{f.name}" for f in (ROOT / "src/m4").iterdir() if f.suffix in m4asm.SOURCE_TYPES}
    assert {p for p in listed_sources() if p.startswith("src/m4/")} == m4


def test_page_lists_the_web_features():
    # the page builds every one, the set whose MD5 a release pins
    page = (ROOT / "web/index.html").read_text()
    assert sorted(re.findall(r'<div class="feat" data-feature="(\w+)">', page)) == sorted(m4cache.web_flags())


@pytest.mark.firmware
def test_page_copy_builds_features_from_the_cache(tmp_path):
    stock = os.environ.get("HX_STOMP_HXF")
    if not stock:
        pytest.skip("HX_STOMP_HXF is not set")
    flags = ["HX_BPM", "HX_LONG_PRESS"]           # a section of its own, and settings in a stock category
    cache = tmp_path / "m4cache.json"
    cache.write_text(json.dumps({"modules": m4cache.modules(stock, flags)}))
    page = tmp_path / "repo"
    for p in listed_sources():
        (page / p).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / p, page / p)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HX_")}
    env.update({f: "1" for f in flags})
    base = m4cache.nam_base(stock, str(tmp_path))      # what build.py, and the page, give patch_menu.py
    out = {}
    for name, root, extra in (("clang", ROOT, {}), ("cache", page, {"HX_M4_CACHE": str(cache)})):
        out[name] = tmp_path / f"{name}.l6ia"
        r = subprocess.run([sys.executable, str(root / "tools/patch_menu.py"), base, str(out[name])],
                           env={**env, **extra}, cwd=root, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    assert out["cache"].read_bytes() == out["clang"].read_bytes()
