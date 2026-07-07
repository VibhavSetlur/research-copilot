from __future__ import annotations

import sys


def _supports_utf8() -> bool:
    """True when stdout encoding looks like UTF-* (else ASCII fallback)."""
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def _glyph(unicode_char: str, ascii_fallback: str) -> str:
    """Return the unicode glyph when stdout is UTF-*, else the ASCII fallback."""
    return unicode_char if _supports_utf8() else ascii_fallback


def _check() -> str:
    return _glyph("✓", "[+]")


def _cross() -> str:
    return _glyph("✗", "[x]")


def _warn_glyph() -> str:
    return _glyph("⚠", "[!]")
