"""
CONSOLE ENCODING BOOTSTRAP

Import this module FIRST — before anything that prints — in every entry-point
script:

    import console_setup  # noqa: F401

Why this is required
────────────────────
Every script in this project prints the rupee sign (U+20B9), box-drawing
characters (U+2554 etc.), check marks (U+2714) and emoji. On Windows, a console
that has not been switched to UTF-8 reports sys.stdout.encoding == 'cp1252',
and cp1252 cannot represent any of them. The first such print raises
UnicodeEncodeError and kills the run — after the market gate has passed and,
in the settlement script, potentially after money-affecting state has been
computed.

Reconfiguring to UTF-8 with errors='replace' makes output degrade to a
replacement glyph in the worst case instead of terminating the process.
sys.stdout.reconfigure() is available on Python 3.7+.
"""

import sys


def _apply() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Stream is redirected to something that cannot be reconfigured
            # (a pipe wrapper, a captured buffer, a test harness). Nothing to
            # do — leave it as-is rather than failing at import time.
            pass


_apply()
