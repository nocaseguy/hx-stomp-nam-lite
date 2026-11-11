"""The on-device QA tools and QA.md name the image this fork's build.py writes."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_qa_tools_name_the_file_build_py_writes():
    written = re.search(r'f"\{unit\}(_v3\.80\.0_\w+\.hxf)"', (ROOT / "build.py").read_text()).group(1)
    for path in ("QA.md", "tools/hx_ramrun.sh", "tools/hx_reamp.py", "tools/hx_smoke.py"):
        names = re.findall(r"build/HX_\w+?(_v3\.80\.0_\w+\.hxf)", (ROOT / path).read_text())
        assert names and set(names) == {written}, path
