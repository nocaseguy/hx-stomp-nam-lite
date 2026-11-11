"""The research notes: INDEX.md lists every note, and every relative link in the docs reaches a file and heading."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def slug(heading):
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(path):
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    return {slug(h) for h in re.findall(r"^#+ (.+)$", text, flags=re.M)}


def docs():
    # The NAM notes at the top of docs/research name files of upstream's working repository, so they're left out.
    notes = [p for p in RESEARCH.rglob("*.md") if p.parent != RESEARCH or p.name in ("INDEX.md", "conventions.md", "tools.md", "ideas.md")]
    return notes + list((ROOT / "docs").glob("*.md")) + [ROOT / "README.md", ROOT / "FIRMWARE_NOTES.md"]


def test_index_lists_every_note():
    listed = {(RESEARCH / m).resolve() for m in LINK.findall((RESEARCH / "INDEX.md").read_text())}
    missing = [str(p.relative_to(RESEARCH)) for p in RESEARCH.rglob("*.md") if p.name != "INDEX.md" and p.resolve() not in listed]
    assert not missing


def test_relative_links_resolve():
    broken = []
    for doc in docs():
        for target in LINK.findall(doc.read_text()):
            if re.match(r"[a-z]+:", target):
                continue
            path, _, anchor = target.partition("#")
            dest = (doc.parent / path).resolve() if path else doc
            if not dest.exists() or (anchor and dest.suffix == ".md" and anchor not in anchors(dest)):
                broken.append(f"{doc.relative_to(ROOT)}: {target}")
    assert not broken
