#!/usr/bin/env python3
"""If HS is active, remind L0 to collect envelopes before stopping."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import format_status, hook_cwd, load_board, session_id_of  # noqa: E402


def _open_work(board: dict) -> bool:
    if not board.get("active"):
        return False
    for node in ((board.get("org") or {}).get("domains") or {}).values():
        status = str(node.get("status") or "")
        if status in ("running", "blocked", "need_input", "escalate"):
            return True
        for worker in node.get("workers") or []:
            if str(worker.get("status") or "") in ("running", "blocked", "need_input"):
                return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    try:
        board = load_board(session_id_of(payload), cwd=hook_cwd(payload))
        if board and _open_work(board):
            msg = (
                "HS still has open domains or workers. Collect remaining envelopes "
                "or /hs-stop before ending.\n" + format_status(board)
            )
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": msg,
                        "systemMessage": msg,
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
