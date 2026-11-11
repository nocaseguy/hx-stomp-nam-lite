"""tools/m4asm.py's precomputed modules (HX_M4_CACHE) and tools/m4cache.py, which makes them at a release for the web page."""
import json

import pytest

import m4asm
import m4cache


def sources(d, **files):
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def test_key_is_the_sources_not_their_paths(tmp_path):
    a = sources(tmp_path / "a", **{"x.s": "nop\n", "y.inc": ".equ Y, 1\n"})
    b = sources(tmp_path / "b", **{"x.s": "nop\n", "y.inc": ".equ Y, 1\n"})
    assert m4asm.key(a / "x.s", (a,)) == m4asm.key(b / "x.s", (b,))


def test_key_follows_every_neighbour(tmp_path):
    a = sources(tmp_path / "a", **{"x.s": "nop\n", "y.inc": ".equ Y, 1\n", "notes.txt": "1"})
    k = m4asm.key(a / "x.s", (a,))
    (a / "notes.txt").write_text("2")                  # not a source
    assert m4asm.key(a / "x.s", (a,)) == k
    (a / "y.inc").write_text(".equ Y, 2\n")
    assert m4asm.key(a / "x.s", (a,)) != k


def test_cached_module(tmp_path, monkeypatch):
    a = sources(tmp_path / "a", **{"x.s": "nop\n"})
    cache = tmp_path / "m4cache.json"
    cache.write_text(json.dumps({"modules": {m4asm.key(a / "x.s", (a,)): {"code": "00bf", "symbols": {"go": 0}}}}))
    monkeypatch.setenv(m4asm.CACHE, str(cache))
    monkeypatch.setattr(m4asm, "CLANG", "/nonexistent/clang")
    assert m4asm.assemble_module(str(a / "x.s"), (a,)) == (b"\x00\xbf", {"go": 0})
    (a / "x.s").write_text("bx lr\n")
    with pytest.raises(SystemExit, match="no code for x.s"):
        m4asm.assemble_module(str(a / "x.s"), (a,))


def test_web_flags_leave_out_gr():
    flags = m4cache.web_flags()
    assert "HX_GR" not in flags
    assert set(flags) == {"HX_TUNER", "HX_BPM", "HX_DSP_METER", "HX_BREATHING_LINE", "HX_LONG_PRESS", "HX_MORE_SNAPSHOTS",
                          "HX_CLICK"}


def test_make_refuses_a_cache_build(monkeypatch):
    monkeypatch.setenv(m4asm.CACHE, "m4cache.json")
    with pytest.raises(SystemExit, match="unset HX_M4_CACHE"):
        m4cache.make("stock.hxf")


def test_release_repo():
    import release
    assert release.repo("https://github.com/wisemandenny/hxtra.git") == "wisemandenny/hxtra"
    assert release.repo("git@github.com:wisemandenny/hxtra.git") == "wisemandenny/hxtra"
    with pytest.raises(SystemExit):
        release.repo("https://example.com/hxtra.git")


@pytest.mark.parametrize("tag, text, ok", [("v1.0.0", "v1.0.0", True), ("v1.0.1", "v1.0.0", False),
                                           ("v1.0.0", "HXtra", True), ("1.0.0", "HXtra", False),
                                           ("v1.1.0-rc.1", "HXtra", True)])
def test_release_version(tag, text, ok):
    import release
    if ok:
        release.check_version(tag, text)
    else:
        with pytest.raises(SystemExit):
            release.check_version(tag, text)
