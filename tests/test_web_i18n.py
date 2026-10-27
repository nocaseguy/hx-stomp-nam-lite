"""web/index.html's translations: every language has every string of the page, with the
same HTML tags and {placeholders} as the English, and is listed in the language menu."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parent.parent / "web/index.html").read_text()


class _Keys(HTMLParser):
    """The English of each data-i18n element: its inner HTML."""
    VOID = {"input", "br", "meta", "link", "img"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.out = [], {}

    def handle_starttag(self, tag, attrs):
        for e in self.stack:
            e[2].append(self.get_starttag_text())
        if tag not in self.VOID:
            self.stack.append([tag, dict(attrs).get("data-i18n"), []])

    def handle_endtag(self, tag):
        e = self.stack.pop()
        if e[1]:
            self.out[e[1]] = "".join(e[2])
        for x in self.stack:
            x[2].append(f"</{tag}>")

    def handle_data(self, d):
        for e in self.stack:
            e[2].append(d)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")


def english():
    p = _Keys()
    p.feed(PAGE[PAGE.index("<body>"):PAGE.index("<script")])
    en = dict(p.out)
    en.update(json.loads(PAGE.split("var EN = ")[1].split("};")[0] + "}"))
    return en


EN = english()
LANGS = json.loads(PAGE.split("// LANGS-BEGIN\nvar LANGS = ")[1].split(";\n// LANGS-END")[0])
NAMES = re.findall(r"(\w+): \"", PAGE.split("var LANG_NAMES = {")[1].split("};")[0])


def tags(s):
    return sorted(re.findall(r"<[^>]+>", s))


def placeholders(s):
    return sorted(re.findall(r"\{\w+\}", s))


def test_menu_lists_every_language():
    assert NAMES[0] == "en" and sorted(NAMES[1:]) == sorted(LANGS) and len(NAMES) == 10


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_language_matches_english(lang):
    t = LANGS[lang]
    assert sorted(t) == sorted(EN), "missing or extra keys"
    assert [k for k in EN if tags(t[k]) != tags(EN[k])] == [], "HTML tags differ"
    assert [k for k in EN if placeholders(t[k]) != placeholders(EN[k])] == [], "placeholders differ"
    assert [k for k in EN if not t[k].strip()] == [], "empty strings"
