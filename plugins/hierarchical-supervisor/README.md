# Hierarchical Supervisor

ZCode plugin that runs the industrial three-layer tree:

```
L0 Top-Supervisor   (current session)
  └── L1 hs-manager (one per domain, max 4)
        └── L2 hs-worker (max 5 per domain)
```

A skill cannot keep this stable. This plugin does, by combining:

- **custom agents** (`hs-manager`, `hs-worker`) with different toolboxes
- **slash commands** (`/hs`, `/hs-status`, `/hs-stop`)
- **hooks** that deny illegal `Agent` spawns while a run is active
- **MCP board** (`hs_start` / `hs_ledger` / `hs_progress` / `hs_replan` / `hs_forward` / `hs_report` / `hs_stop`) so supervisors see ledgers, not inner monologue

Children do **not** inherit parent chat. Briefs must be self-contained. Mail is envelopes.

## Install

1. Settings → Plugin Management → Discover → **+** marketplace
2. Add GitHub `LotoLe/zcode-hierarchical-supervisor`, or this local directory: `~/.zcode/cli/plugins/marketplaces/zcode-local`
3. Install **hierarchical-supervisor** and enable it
4. New session, type `/hs`

If this directory is already the marketplace checkout:

```bash
cd ~/.zcode/cli/plugins/marketplaces/zcode-local
git pull
```

Then start a new ZCode session so agents, hooks, and MCP reload.

## Use

```
/hs 给登录接口补测试和文档
```

L0 splits domains (e.g. `test`, `docs`), spawns one `hs-manager` each, managers spawn `hs-worker`s. You get a synthesized report, not worker transcripts.

```
/hs-status
/hs-stop
```

## Protocol (short)

- L0 may spawn `hs-manager` (and `Explore`). Must not spawn `hs-worker`.
- L1 may spawn `hs-worker` only. Max 5 per domain.
- L2 must not call `Agent`.
- Every L1/L2 brief includes `HS-DOMAIN:`, `GOAL:`, `DONE WHEN:` (hook-enforced).
- Task Ledger (`hs_ledger`) at start; Progress Ledger (`hs_progress`) every L0/L1 step.
- `max_stalls=3` triggers replan: mark agents stale, spawn new ones, do not SendMessage a stale worker.
- Envelopes: `progress | need_input | blocked | done | escalate`. Use `hs_forward` to pass L1 evidence verbatim.
- Browser / desktop stay at L0.
- Escalate to the human only for irreversible, security, missing auth, or a real product choice.

## Board location

- Workspace: `<project>/.zcode/hs/board.json`
- Fallback: plugin data dir under `~/.zcode/cli/plugins/data/`

## Limits of this v0.2

- Hook sees the caller mainly via `agent_type` (`zcode-hs-manager` / `zcode-hs-worker`). If ZCode reports a generic name, L1/L2 enforcement is weaker and L0 still cannot skip to workers while the board is active.
- There is no `SubagentStop` event; process visibility is envelopes + the board, not live traces.
- MCP tools are the preferred board API; `/hs` still works if MCP is slow to connect, via the JSON file.

## Dev

```bash
python3 tests/test_hs_board.py
```
