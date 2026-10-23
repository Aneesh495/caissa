"""Compatibility entry point for the bounded protocol campaign."""

if __package__ in [None, ""]:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.protocol_campaign import main

if __name__ == "__main__":
    raise SystemExit(main())
