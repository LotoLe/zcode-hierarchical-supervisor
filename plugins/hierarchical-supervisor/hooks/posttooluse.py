#!/usr/bin/env python3
"""Attach spawned agent ids onto the HS org chart after Agent returns."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import attach_spawn, hook_cwd  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    try:
        attach_spawn(payload, cwd=hook_cwd(payload))
    except Exception:
        pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
