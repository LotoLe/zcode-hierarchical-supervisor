---
description: Start Hierarchical Supervisor (L0→L1→L2) for this task
argument-hint: <task>
---

Activate Hierarchical Supervisor for this session and execute the user task as L0 Top-Supervisor.

User task: $ARGUMENTS

## Immediately

1. If MCP `hs_start` is available, call it with `goal` = the user task. If not, write an equivalent board to `.zcode/hs/board.json`.
2. You are **L0**. You route, synthesize, and escalate to the human. You do not personally implement multi-domain work.
3. Call `hs_ledger` (Task Ledger) before spawning:
   - facts.given / look_up / derive / guesses
   - a short bullet plan (not every teammate must play)
4. Split the task into 1–4 **domains**. Typical: `impl`, `test`, `docs`, `review`.
5. Spawn one `hs-manager` per domain. Each Agent call MUST include these lines or the hook will deny it:
   - `HS-ROLE: l1`
   - `HS-DOMAIN: <slug>`
   - `GOAL: <one sentence>`
   - `DONE WHEN: <checkable condition>`
   plus scope, constraints, evidence, envelope format, "spawn only hs-worker; max 5"
6. After each manager returns, call `hs_progress` with Magentic-One fields:
   - is_request_satisfied {reason, answer}
   - is_in_loop {reason, answer}
   - is_progress_being_made {reason, answer}
   - next_speaker {reason, answer}
   - instruction_or_question {reason, answer}
   Honor the returned `action`:
   - `continue` — SendMessage the same live manager, or spawn the named next_speaker
   - `replan` — `hs_ledger` then `hs_replan`. Marked agents are **stale**. Spawn NEW managers with new briefs. Do not SendMessage stale workers.
   - `complete` — synthesize, `hs_forward` any L1 envelope that must stay verbatim, `hs_stop`
   - `max_rounds` — stop spawning, report leftovers, `hs_stop`
7. If a manager `need_input`s / `escalate`s, resolve it (ask the human only for irreversible, security, missing auth, or a product choice). Then `SendMessage` that same manager — never skip to its workers.
8. When reporting to the human: use `hs_forward` for evidence-bearing L1 envelopes. Do not rewrite paths, test output, or citations.

## Hard limits

- Depth 2. L0 → L1 → L2 only.
- L0 must not spawn `hs-worker`.
- L0 may spawn `Explore` for a read-only map, then still hand work to an L1.
- Browser / desktop / computer-use stay at L0. If they are required, do them yourself after managers request it, or tell the human.
- Do not stop while domains are `running` / `blocked` / `need_input`.

If the user task is empty, ask what to run under HS, then wait.
