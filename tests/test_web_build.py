"""web/firmware-worker.js, the in-browser build.py: it accepts the same stock files,
pins the same built MD5s, and loads every file the build reads."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER = (ROOT / "web/firmware-worker.js").read_text()


def js_object(name):
    body = re.search(name + r" = \{(.*?)\};", WORKER, re.S).group(1)
    return dict(re.findall(r'"(\w+)": "(\w+)"', body))


def py_dict(path, name):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == name)
    return ast.literal_eval(node.value)


def test_stock_md5_as_build_py():
    assert js_object("STOCK_MD5") == py_dict("build.py", "STOCK_MD5")


def test_kernel_as_build_py():
    body = re.search(r"var KERNEL = \{(.*?)\};", WORKER, re.S).group(1)
    js = {u: (k, re.findall(r'"([^"]+)"', opts)) for u, k, opts in
          re.findall(r'"(\w+)": \["([\w/.]+)", \[(.*?)\]\]', body)}
    assert js == {u: (k, list(o)) for u, (k, o) in py_dict("build.py", "KERNEL").items()}


def test_built_md5_as_firmware_test():
    pinned = py_dict("tests/test_firmware.py", "BUILT_MD5")
    assert js_object("BUILT_MD5") == {"HX_Stomp": pinned["HX_STOMP_HXF"], "HX_Stomp_XL": pinned["HX_STOMP_XL_HXF"]}


def test_sources_cover_the_build():
    listed = set(re.findall(r'"(tools/[\w/.]+)"', WORKER.split("var SOURCES")[1].split("];")[0]))
    assert all((ROOT / p).is_file() for p in listed)
    # every module the build's scripts import, and every file they open next to themselves
    need = {"tools/hxf.py", "tools/l6ia.py", "tools/l6ia_verify.py", "tools/patch_amp.py",
            "tools/sharc/nam_lite.py", "tools/sharc/nam_lite_kernel.asm",
            "tools/sharc/nam_multi.py", "tools/sharc/nam_multi_kernel.asm"}
    for d in ("tools", "tools/sharc"):
        for f in listed:
            if not f.endswith(".py"):
                continue
            for mod in re.findall(r"^import (\w+)", (ROOT / f).read_text(), re.M):
                if (ROOT / d / f"{mod}.py").is_file():
                    need.add(f"{d}/{mod}.py")
            for name in re.findall(r"""['"](\w+\.(?:json|asm))['"]""", (ROOT / f).read_text()):
                if (ROOT / d / name).is_file() and d == str(Path(f).parent):
                    need.add(f"{d}/{name}")
    assert need - {"tools/sharc/nam_a2.asm"} <= listed
