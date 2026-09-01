#!/usr/bin/env python3
"""Compatibility entrypoint for the quarantined indicator experiment."""

from __future__ import annotations

import sys

from app.devtools.rokid_led import quarantine_reason


def main(argv: list[str] | None = None) -> int:
    del argv
    print(quarantine_reason(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
