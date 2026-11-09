"""Prompt helpers so the standalone test scripts can run unattended.

The DICOM-ingest test scripts (``test_task1_*``, ``test_task3_*``) used to call
``input()`` directly for confirmations and menu choices.  Run non-interactively
that raised ``EOFError`` and aborted the script part way through.

Enable non-interactive mode with either::

    DRAW_TESTS_NON_INTERACTIVE=1 python dicom_handler/tests/test_task3_deidentify_series.py
    python dicom_handler/tests/test_task3_deidentify_series.py --non-interactive

When non-interactive (or when stdin is closed / raises ``EOFError``) the helpers
return the safe default the prompt would have used, so the suite always runs to
completion and cleans up (including destroying its test database).
"""
from __future__ import annotations

import os
import sys

_NON_INTERACTIVE = (
    os.environ.get("DRAW_TESTS_NON_INTERACTIVE", "").lower() in ("1", "true", "yes")
    or "--non-interactive" in sys.argv
    or "-n" in sys.argv
)

# Strip our flags so they don't leak into argparse-based scripts sharing argv.
for _flag in ("--non-interactive", "-n"):
    while _flag in sys.argv:
        sys.argv.remove(_flag)


def non_interactive() -> bool:
    return _NON_INTERACTIVE


def ask(prompt: str, default: str = "") -> str:
    """Read a line from stdin (stripped).  Returns ``default`` in
    non-interactive mode or on ``EOFError``."""
    if _NON_INTERACTIVE:
        print(f"{prompt}[non-interactive -> {default!r}]")
        return default
    try:
        return input(prompt).strip()
    except EOFError:
        print(f"{prompt}[stdin closed -> {default!r}]")
        return default


def confirm(prompt: str, default: bool = False) -> bool:
    """Yes/no question; returns ``default`` in non-interactive mode or on EOF."""
    return ask(prompt, "y" if default else "n").lower() in ("y", "yes")
