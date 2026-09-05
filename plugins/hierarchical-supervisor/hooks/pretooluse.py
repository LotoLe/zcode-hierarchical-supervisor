#!/usr/bin/env python3
"""Deny illegal Agent spawns while Hierarchical Supervisor is active."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import (  # noqa: E402
    evaluate_agent_spawn,
    hook_cwd,
    note_pending_spawn,
)


def _payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def main() -> int:
    payload = _payload()
    try:
        decision = evaluate_agent_spawn(payload, cwd=hook_cwd(payload))
        if not decision.get("allow"):
            reason = str(decision.get("reason") or "HS spawn denied")
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        },
                        "systemMessage": reason,
                    }
                )
            )
            return 0
        note_pending_spawn(payload, decision, cwd=hook_cwd(payload))
        print(json.dumps({}))
        return 0
    except Exception as exc:
        print(json.dumps({"systemMessage": f"HS hook error (allowed): {exc}"}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
