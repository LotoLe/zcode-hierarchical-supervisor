#!/usr/bin/env python3
"""Keep the L0 protocol card in context while a run is active."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import hook_cwd, load_board, protocol_card, session_id_of  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    try:
        board = load_board(session_id_of(payload), cwd=hook_cwd(payload))
        if board and board.get("active"):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": protocol_card(board),
                        }
                    }
                )
            )
            return 0
    except Exception:
        pass
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
