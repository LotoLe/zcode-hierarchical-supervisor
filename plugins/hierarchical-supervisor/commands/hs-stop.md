---
description: Stop Hierarchical Supervisor for this session
argument-hint: optional reason
---

Deactivate Hierarchical Supervisor.

Reason: $ARGUMENTS

1. Call MCP `hs_stop` with the reason (default `stopped by user`). If MCP is missing, set `active=false` on `.zcode/hs/board.json`.
2. Confirm to the human: stopped, last org snapshot, anything still open.
3. Do not spawn further HS agents after stopping. Normal tools resume.
