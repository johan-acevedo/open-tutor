"""Locale tables for fixed spoken/shown lines (Swedish default).

Add e.g. locales/en.py later with the same names; get_locale() falls back to
Swedish for unknown locales so current sessions keep working.
"""

from __future__ import annotations

from types import ModuleType

from . import sv as _sv


def get_locale(locale: str | None) -> ModuleType:
    loc = (locale or "sv").strip().lower()
    # Only Swedish exists for now; every other request falls back to it.
    return _sv


def locale_id(locale: str | None) -> str:
    get_locale(locale)  # validate through the same fallback
    loc = (locale or "sv").strip().lower()
    return loc if loc else "sv"
