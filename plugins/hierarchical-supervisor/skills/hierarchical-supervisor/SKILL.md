---
name: hierarchical-supervisor
description: "Run the L0/L1/L2 Hierarchical Supervisor protocol. Use when the user invokes /hs, asks for 分层监督者, Top-Supervisor, domain managers and workers, or a stable multi-agent tree. Do not use for a single-file edit or a question that needs no dispatch."
---

# Hierarchical Supervisor

Industrial tree, depth 2:

```
L0 Top-Supervisor (this session)
  └── L1 hs-manager (one per domain, max 4)
        └── L2 hs-worker (max 5 per domain)
```

Children **do not inherit chat history**. Briefs must be self-contained. Mail is envelopes, not transcripts.

## When this skill is in force

- User ran `/hs`
- Board file exists and `active: true`
- MCP `hs_status` shows an active run

Leave the protocol with `/hs-stop`.

## Roles

| Layer | Agent | May spawn | Must not |
|---|---|---|---|
| L0 | current session | `hs-manager`, `Explore` | `hs-worker`, implementation of multi-domain work |
| L1 | `hs-manager` | `hs-worker` only | another manager, browser, publish |
| L2 | `hs-worker` | nobody | Agent, sibling chat, browser |

## Brief template (copy into every Agent prompt)

Hook **denies** L1/L2 spawns missing `HS-DOMAIN`, `GOAL`, or `DONE WHEN`.

```
HS-ROLE: l1|l2
HS-DOMAIN: <slug>
GOAL: ...
DONE WHEN: ...
SCOPE: ...
OUT OF SCOPE: ...
CONSTRAINTS: ...
FILES: ...
REPORT WITH: HS-ENVELOPE (progress|need_input|blocked|done|escalate)
```

## Ledgers (Magentic-One)

Outer loop — `hs_ledger` once at start, rewrite on replan:

- given facts / facts to look up / facts to derive / educated guesses
- short bullet plan

Inner loop — `hs_progress` after every L1 return:

```
is_request_satisfied, is_in_loop, is_progress_being_made,
next_speaker, instruction_or_question
```

`n_stalls` rises when looping or not moving, falls when moving. At `max_stalls` (3) the action is `replan`: `hs_replan`, mark live agents stale, spawn **new** agents. Do not patch a stale session with SendMessage.

`hs_forward` passes an L1 envelope to the human verbatim (do not rewrite evidence).

## Envelopes

```
HS-ENVELOPE
from: l0|l1:<domain>|l2:<domain>
type: progress|need_input|blocked|done|escalate
domain: <slug>
summary: ...
evidence:
- ...
next: ...
```

L1 synthesizes worker envelopes into one L1 envelope. L0 synthesizes L1 envelopes for the human.

## Sensors

- Direct: child final reply (only native guaranteed path)
- Board: MCP `hs_report` / `.zcode/hs/board.json`
- Enforcement: plugin PreToolUse hook denies illegal `Agent` spawns while the run is active

There is no live view of a child's chain-of-thought. Do not pretend there is.

## Failure

1. L2 fails → L1 retries once with a tighter brief
2. L1 still stuck → `escalate` to L0
3. L0 `hs_progress` says replan → new Task Ledger, `hs_replan`, spawn fresh L1
4. L0 cannot decide without the human → ask (irreversible, security, auth, product choice only)

## L0 algorithm

1. `hs_start`
2. `hs_ledger` (facts + plan)
3. Split domains (1–4) and spawn L1 managers (complete briefs)
4. On each return: `hs_progress`; honor `continue|replan|complete|max_rounds`
5. `hs_forward` evidence-bearing envelopes; `hs_stop`
