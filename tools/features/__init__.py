"""features - the CustomOS features tools/patch_menu.py builds in: one module a feature, named by its file.

A feature module may have:
  FLAG       the environment variable that turns it on (HX_BPM=1 python3 build.py ...), a tuple of them (on when any is set), or
             None (the default) for always on; any non-empty value turns it on, and apply(p) reads the value with p.input(FLAG)
  INPUTS     Input()s: the environment variables it reads besides FLAG, or FLAG itself to give its value a kind
  ORDER      its turn among the features (default 100): the order of their CustomOS pages and of their handlers on a shared hook
  CONFLICTS  names of features it cannot be built with
  SETTINGS   Setting()s on its own CustomOS pages, three to a page; each takes the ID tools/setting_ids.py gives '<feature>.<key>'
  apply(p)   its code and hooks, through tools/patch_menu.py's Patch: p.put() (a write no other feature may overlap), p.expect(),
             p.add() (bytes into the code cave), p.module() (an M4 .s assembled at build time), p.chain_ptr(), p.chain_bl() and
             p.chain_entry() (handlers on a hook other features may share), p.own_entry() (a function start for this feature
             alone, for a handler no chain can take), p.id('<feature>.<key>'), p.input('<VAR>'), p.entry(n) (Entry n by
             offset: read(), expect(), expect_md5(), and put(), checked for overlap as p.put() is; Entry 8 also add_item()) and
             p.add_glyph() (a glyph in an empty slot of an Entry 7 font); tools/image_store.py reads Entries 7 and 8.
             The web build imports every feature file, so a module imports only what Pyodide has at its top, and runs a
             tool such as sips only inside apply(p).

An M4 .s file gets `.include "customos.inc"`, generated at build time: SETTING_<FEATURE>_<KEY> (the ID), ..._MAX and ..._DEFAULT for
every setting, and the macro CUSTOMOS_SETTING_GET, a function customos_setting_get (r0 ID, r1 max, r2 default -> r0 the value, the
default when it is unset or above max: a unit may hold a value stored by another build).
"""
import importlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Input:
    var: str                # the environment variable
    default: str = None     # the text used when the variable is unset or empty, checked as a set value is
    choices: tuple = None   # the values it may take
    path: bool = False      # a file, relative to the directory the build started in; it must exist
    mapping: bool = False   # 'key=value,key=value' -> {key: value} (each value a path when path is set); unset is {}


@dataclass(frozen=True)
class Setting:
    key: str
    label: bytes            # b'Section\nName', at most 8 characters before the newline and 9 after it, as the stock labels
    values: tuple           # the value strings, value 0 first; at most 19 bytes each
    default: int = 0        # what a reset sets; an unset ID reads 0

    @property
    def max(self):
        return len(self.values) - 1


def name(feature):
    return feature.__name__.rsplit('.', 1)[1]


def load():
    """Every feature module, in ORDER then name."""
    here = os.path.dirname(os.path.abspath(__file__))
    mods = [importlib.import_module(f'{__name__}.{f[:-3]}') for f in sorted(os.listdir(here))
            if f.endswith('.py') and not f.startswith('_')]
    return sorted(mods, key=lambda m: (getattr(m, 'ORDER', 100), name(m)))


def flags(feature):
    f = getattr(feature, 'FLAG', None)
    return (f,) if isinstance(f, str) else tuple(f or ())


def inputs(feature):
    """Its Input()s by variable: INPUTS, and each FLAG not among them as plain text."""
    out = {f: Input(f) for f in flags(feature)}
    out.update((i.var, i) for i in getattr(feature, 'INPUTS', ()))
    return out


def value(feature, i, raw, cwd=None):
    """An input's value from its environment variable's text raw."""
    raw = raw or i.default
    if raw is None:
        return {} if i.mapping else None
    pairs = [kv.partition('=') for kv in raw.split(',')] if i.mapping else [('', '=', raw)]
    if any(not eq or not v for _, eq, v in pairs):
        raise SystemExit(f'{name(feature)}: {i.var} takes key=value pairs separated by commas, not {raw!r}')
    out = {}
    for k, _, v in pairs:
        if i.choices is not None and v not in i.choices:
            raise SystemExit(f'{name(feature)}: {i.var} is one of {", ".join(i.choices)}, not {v!r}')
        if i.path:
            v = os.path.join(cwd or os.getcwd(), os.path.expanduser(v))
            if not os.path.isfile(v):
                raise SystemExit(f'{name(feature)}: {i.var}: no file {v}')
        out[k] = v
    return out if i.mapping else out['']


def values(feature, env=os.environ, cwd=None):
    """{variable: value} of its inputs, each checked: a wrong one fails the build before any feature is applied."""
    return {var: value(feature, i, env.get(var), cwd) for var, i in inputs(feature).items()}


def enabled(mods, env=os.environ):
    on = [m for m in mods if not flags(m) or any(env.get(f) for f in flags(m))]
    names = {name(m) for m in on}
    for m in on:
        clash = names & set(getattr(m, 'CONFLICTS', ()))
        if clash:
            raise SystemExit(f'patch-menu: {name(m)} cannot be built with {", ".join(sorted(clash))}')
    return on
