"""features - the CustomOS features tools/patch_menu.py builds in: one module a feature, named by its file.

A feature module may have:
  FLAG       the environment variable that turns it on (HX_BPM=1 python3 build.py ...), or None (the default) for always on
  ORDER      its turn among the features (default 100): the order of their CustomOS pages and of their handlers on a shared hook
  CONFLICTS  names of features it cannot be built with
  SETTINGS   Setting()s on its own CustomOS pages, three to a page; each takes the ID tools/setting_ids.py gives '<feature>.<key>'
  apply(p)   its code and hooks, through tools/patch_menu.py's Patch: p.put() (a write no other feature may overlap), p.expect(),
             p.add() (bytes into the code cave), p.module() (an M4 .s assembled at build time), p.chain_ptr(), p.chain_bl() and
             p.chain_entry() (handlers on a hook other features may share), p.id('<feature>.<key>')

An M4 .s file gets `.include "customos.inc"`, generated at build time: SETTING_<FEATURE>_<KEY> (the ID), ..._MAX and ..._DEFAULT for
every setting, and the macro CUSTOMOS_SETTING_GET, a function customos_setting_get (r0 ID, r1 max, r2 default -> r0 the value, the
default when it is unset or above max: a unit may hold a value stored by another build).
"""
import importlib
import os
from dataclasses import dataclass


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


def enabled(mods, env=os.environ):
    on = [m for m in mods if not getattr(m, 'FLAG', None) or env.get(m.FLAG)]
    names = {name(m) for m in on}
    for m in on:
        clash = names & set(getattr(m, 'CONFLICTS', ()))
        if clash:
            raise SystemExit(f'patch-menu: {name(m)} cannot be built with {", ".join(sorted(clash))}')
    return on
