---
description: Show the Hierarchical Supervisor org chart and recent envelopes
---

Report the current Hierarchical Supervisor board.

1. Call MCP `hs_status` if available. Otherwise read `.zcode/hs/board.json` (workspace) or explain that no run is active.
2. Show the human: active flag, goal, each domain's L1 status, each worker status, last 6 envelopes.
3. Do not start a new run. Do not spawn agents unless the human then asks.
