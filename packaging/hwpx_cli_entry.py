# -*- coding: utf-8 -*-
"""PyInstaller용 HWPX Filler CLI 진입점."""

import sys

from hwpxfiller.cli import main


def _force_utf8_output() -> None:
    """Keep Korean CLI output safe when a Windows runner redirects its console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    _force_utf8_output()
    raise SystemExit(main())
