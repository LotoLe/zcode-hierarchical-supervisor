"""Session-scoped org chart and postal board for Hierarchical Supervisor."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BOARD_VERSION = 2
MAX_L1 = 4
MAX_L2_PER_L1 = 5
MAX_EVENTS = 80
MAX_DEPTH = 2
MAX_STALLS = 3
MAX_ROUNDS = 24
ENVELOPE_TYPES = ("progress", "need_input", "blocked", "done", "escalate")
MANAGER_MARK = "hs-manager"
WORKER_MARK = "hs-worker"
EXPLORE_MARKS = frozenset({"explore", "Explore"})
ACTIVE_WORKER_STATUSES = frozenset({"running", "blocked", "need_input", "escalate", ""})

DOMAIN_RE = re.compile(r"HS-DOMAIN:\s*([A-Za-z0-9_.:-]+)", re.I)
GOAL_RE = re.compile(r"^\s*GOAL:\s*\S", re.I | re.M)
DONE_WHEN_RE = re.compile(r"^\s*DONE[\s_-]*WHEN:\s*\S", re.I | re.M)
AGENT_ID_RE = re.compile(r"agent_[A-Za-z0-9._-]+")
REQUIRED_BRIEF_FIELDS = ("HS-DOMAIN", "GOAL", "DONE WHEN")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def plugin_data_dir() -> Path:
    raw = os.environ.get("ZCODE_PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if raw:
        return Path(raw)
    return Path.home() / ".zcode/cli/plugins/data/hierarchical-supervisor@zcode-local"


def project_dir(cwd: Optional[str] = None) -> Optional[Path]:
    raw = os.environ.get("ZCODE_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    return Path(raw) if raw else None


def session_id_of(payload: Optional[Dict[str, Any]] = None) -> str:
    payload = payload or {}
    return (
        str(payload.get("session_id") or "")
        or os.environ.get("ZCODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or "unknown"
    )


def board_paths(session_id: str, cwd: Optional[str] = None) -> List[Path]:
    paths: List[Path] = []
    proj = project_dir(cwd)
    if proj:
        paths.append(proj / ".zcode" / "hs" / "board.json")
    paths.append(plugin_data_dir() / "boards" / f"{session_id}.json")
    # de-dupe while preserving order
    seen = set()
    out: List[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def empty_task_ledger() -> Dict[str, Any]:
    return {
        "facts": {
            "given": "",
            "look_up": "",
            "derive": "",
            "guesses": "",
        },
        "facts_text": "",
        "plan": "",
        "updated_at": "",
    }


def empty_progress() -> Dict[str, Any]:
    return {
        "n_rounds": 0,
        "n_stalls": 0,
        "replan_count": 0,
        "action": "continue",
        "last": None,
    }


def empty_board(session_id: str, goal: str = "") -> Dict[str, Any]:
    return {
        "version": BOARD_VERSION,
        "active": True,
        "session_id": session_id,
        "goal": goal.strip(),
        "started_at": _now(),
        "updated_at": _now(),
        "limits": {
            "max_l1": MAX_L1,
            "max_l2_per_l1": MAX_L2_PER_L1,
            "max_depth": MAX_DEPTH,
            "max_stalls": MAX_STALLS,
            "max_rounds": MAX_ROUNDS,
        },
        "org": {
            "l0": {"status": "running"},
            "domains": {},
        },
        "task_ledger": empty_task_ledger(),
        "progress": empty_progress(),
        "events": [],
        "pending_spawns": [],
        "forwarded": [],
    }


def _migrate(board: Dict[str, Any]) -> Dict[str, Any]:
    board.setdefault("task_ledger", empty_task_ledger())
    board.setdefault("progress", empty_progress())
    board.setdefault("forwarded", [])
    limits = board.setdefault("limits", {})
    limits.setdefault("max_l1", MAX_L1)
    limits.setdefault("max_l2_per_l1", MAX_L2_PER_L1)
    limits.setdefault("max_depth", MAX_DEPTH)
    limits.setdefault("max_stalls", MAX_STALLS)
    limits.setdefault("max_rounds", MAX_ROUNDS)
    try:
        board["version"] = max(int(board.get("version") or 1), BOARD_VERSION)
    except (TypeError, ValueError):
        board["version"] = BOARD_VERSION
    return board


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _lock_exclusive(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not lock.exists() or lock.stat().st_size == 0:
        lock.write_bytes(b"0")
    with open(lock, "r+b") as lf:
        _lock_exclusive(lf)
        try:
            fd, tmp = tempfile.mkstemp(prefix=".hs-board-", suffix=".json", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        finally:
            _unlock(lf)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def load_board(session_id: str, cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    chosen: Optional[Dict[str, Any]] = None
    chosen_updated = ""
    for path in board_paths(session_id, cwd):
        data = _read_json(path)
        if not data:
            continue
        updated = str(data.get("updated_at") or data.get("started_at") or "")
        if chosen is None or updated >= chosen_updated:
            chosen = data
            chosen_updated = updated
    return _migrate(chosen) if chosen else None


def save_board(board: Dict[str, Any], cwd: Optional[str] = None) -> List[str]:
    board["updated_at"] = _now()
    session_id = str(board.get("session_id") or "unknown")
    written: List[str] = []
    for path in board_paths(session_id, cwd):
        _atomic_write(path, board)
        written.append(str(path))
    return written


def start_run(session_id: str, goal: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    board = empty_board(session_id, goal)
    save_board(board, cwd)
    return board


def stop_run(session_id: str, cwd: Optional[str] = None, reason: str = "stopped") -> Optional[Dict[str, Any]]:
    board = load_board(session_id, cwd)
    if not board:
        return None
    board["active"] = False
    board["org"]["l0"]["status"] = "stopped"
    board["stop_reason"] = reason
    _append_event(board, from_role="l0", etype="progress", summary=f"run stopped: {reason}", domain=None)
    save_board(board, cwd)
    return board


def _append_event(
    board: Dict[str, Any],
    from_role: str,
    etype: str,
    summary: str,
    domain: Optional[str] = None,
    evidence: Optional[List[str]] = None,
) -> None:
    events: List[Dict[str, Any]] = list(board.get("events") or [])
    events.append(
        {
            "ts": _now(),
            "from": from_role,
            "type": etype,
            "domain": domain,
            "summary": summary[:2000],
            "evidence": (evidence or [])[:12],
        }
    )
    board["events"] = events[-MAX_EVENTS:]


def slug_domain(raw: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (raw or "").strip())[:40].strip("-").lower()
    return text or "general"


def extract_domain(text: str) -> Optional[str]:
    if not text:
        return None
    match = DOMAIN_RE.search(text)
    if match:
        return slug_domain(match.group(1))
    return None


def missing_brief_fields(text: str) -> List[str]:
    missing: List[str] = []
    if not extract_domain(text):
        missing.append("HS-DOMAIN")
    if not GOAL_RE.search(text or ""):
        missing.append("GOAL")
    if not DONE_WHEN_RE.search(text or ""):
        missing.append("DONE WHEN")
    return missing


def _norm(value: Any) -> str:
    return str(value or "").strip()


def caller_kind(payload: Dict[str, Any]) -> str:
    name = " ".join(
        [
            _norm(payload.get("agent_type")),
            _norm(payload.get("agentName")),
            _norm(payload.get("agent_name")),
        ]
    ).lower()
    if WORKER_MARK in name:
        return "l2"
    if MANAGER_MARK in name:
        return "l1"
    return "l0"


def spawn_kind(subagent_type: Any) -> str:
    name = _norm(subagent_type) or "general-purpose"
    lowered = name.lower()
    if WORKER_MARK in lowered:
        return "l2"
    if MANAGER_MARK in lowered:
        return "l1"
    if name in EXPLORE_MARKS or lowered == "explore":
        return "explore"
    return "other"


def _tool_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("tool_input") or payload.get("toolInput") or {}
    return raw if isinstance(raw, dict) else {}


def _subagent_type(payload: Dict[str, Any]) -> str:
    inp = _tool_input(payload)
    return _norm(inp.get("subagent_type") or inp.get("subagentType")) or "general-purpose"


def _prompt_blob(payload: Dict[str, Any]) -> str:
    inp = _tool_input(payload)
    parts = [inp.get("prompt"), inp.get("description"), inp.get("task")]
    return "\n".join(_norm(p) for p in parts if p)


def l1_count(board: Dict[str, Any]) -> int:
    names = set(((board.get("org") or {}).get("domains") or {}).keys())
    for pending in board.get("pending_spawns") or []:
        if pending.get("kind") == "l1" and pending.get("domain"):
            names.add(str(pending["domain"]))
    return len(names)


def l2_count(board: Dict[str, Any], domain: str) -> int:
    domain_node = ((board.get("org") or {}).get("domains") or {}).get(domain) or {}
    workers = [
        w
        for w in (domain_node.get("workers") or [])
        if str(w.get("status") or "running") in ACTIVE_WORKER_STATUSES
    ]
    pending = [
        p
        for p in (board.get("pending_spawns") or [])
        if p.get("kind") == "l2" and p.get("domain") == domain
    ]
    return len(workers) + len(pending)


def infer_domain(payload: Dict[str, Any], board: Optional[Dict[str, Any]] = None) -> str:
    blob = _prompt_blob(payload)
    found = extract_domain(blob)
    if found:
        return found
    if caller_kind(payload) == "l1" and board:
        domains = list(((board.get("org") or {}).get("domains") or {}).keys())
        if len(domains) == 1:
            return domains[0]
        # Prefer a domain whose manager is still running and under capacity.
        for name, node in ((board.get("org") or {}).get("domains") or {}).items():
            if node.get("status") in (None, "running", "blocked", "need_input"):
                return name
        if domains:
            return domains[0]
    desc = _norm(_tool_input(payload).get("description"))
    return slug_domain(desc or "general")


def evaluate_agent_spawn(payload: Dict[str, Any], cwd: Optional[str] = None) -> Dict[str, Any]:
    """Return a decision dict consumed by the PreToolUse hook."""
    session_id = session_id_of(payload)
    board = load_board(session_id, cwd or payload.get("cwd"))
    if not board or not board.get("active"):
        return {"allow": True, "reason": "hs inactive"}

    tool = _norm(payload.get("tool_name") or payload.get("toolName"))
    if tool not in ("Agent", "Task"):
        return {"allow": True, "reason": "not agent"}

    caller = caller_kind(payload)
    kind = spawn_kind(_subagent_type(payload))
    domain = infer_domain(payload, board)
    limits = board.get("limits") or {}
    max_l1 = int(limits.get("max_l1") or MAX_L1)
    max_l2 = int(limits.get("max_l2_per_l1") or MAX_L2_PER_L1)
    progress = board.get("progress") or {}
    max_rounds = int(limits.get("max_rounds") or MAX_ROUNDS)
    if int(progress.get("n_rounds") or 0) >= max_rounds and kind in ("l1", "l2"):
        return {
            "allow": False,
            "reason": f"HS max_rounds={max_rounds} reached. Call hs_progress with is_request_satisfied=true, or /hs-stop, or replan via hs_ledger.",
        }

    if kind in ("l1", "l2"):
        missing = missing_brief_fields(_prompt_blob(payload))
        if missing:
            return {
                "allow": False,
                "reason": (
                    "HS brief is incomplete. Every L1/L2 Agent prompt must include "
                    + ", ".join(f"`{f}:`" for f in missing)
                    + ". Children do not inherit chat history."
                ),
            }

    if caller == "l2":
        return {
            "allow": False,
            "reason": "L2 worker cannot spawn. Report to your L1 manager with an envelope; do not call Agent.",
        }
    if caller == "l1":
        if kind != "l2":
            return {
                "allow": False,
                "reason": "L1 may only spawn subagent_type hs-worker (or hierarchical-supervisor:hs-worker). Put HS-DOMAIN: <name> in the brief.",
            }
        if l2_count(board, domain) >= max_l2:
            return {
                "allow": False,
                "reason": f"L1 domain '{domain}' already has {max_l2} workers. Reuse or wait; do not fan out further.",
            }
        return {"allow": True, "reason": "l1->l2", "domain": domain, "kind": kind, "caller": caller}
    # L0
    if kind == "l2":
        return {
            "allow": False,
            "reason": "L0 cannot skip L1. Spawn hs-manager per domain; that manager spawns hs-worker.",
        }
    if kind == "l1":
        if l1_count(board) >= max_l1:
            return {
                "allow": False,
                "reason": f"L0 already has {max_l1} domain managers. Merge domains or wait.",
            }
        return {"allow": True, "reason": "l0->l1", "domain": domain, "kind": kind, "caller": caller}
    if kind == "explore":
        return {"allow": True, "reason": "l0 explore", "domain": domain, "kind": kind, "caller": caller}
    return {
        "allow": False,
        "reason": "HS is active. L0 may spawn hs-manager (or Explore). Use /hs-stop to leave hierarchical mode.",
    }


def note_pending_spawn(payload: Dict[str, Any], decision: Dict[str, Any], cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not decision.get("allow") or decision.get("reason") == "hs inactive":
        return load_board(session_id_of(payload), cwd)
    if decision.get("kind") not in ("l1", "l2"):
        return load_board(session_id_of(payload), cwd)
    session_id = session_id_of(payload)
    board = load_board(session_id, cwd or payload.get("cwd"))
    if not board or not board.get("active"):
        return board
    pending = list(board.get("pending_spawns") or [])
    pending.append(
        {
            "ts": _now(),
            "kind": decision.get("kind"),
            "caller": decision.get("caller"),
            "domain": decision.get("domain"),
            "subagent_type": _subagent_type(payload),
            "description": _norm(_tool_input(payload).get("description"))[:120],
        }
    )
    board["pending_spawns"] = pending[-20:]
    save_board(board, cwd or payload.get("cwd"))
    return board


def _extract_agent_id(payload: Dict[str, Any]) -> Optional[str]:
    blobs: List[str] = []
    for key in ("tool_response", "tool_result", "toolResult", "toolResponse"):
        val = payload.get(key)
        if isinstance(val, (dict, list)):
            blobs.append(json.dumps(val, ensure_ascii=False))
        elif val:
            blobs.append(str(val))
    text = "\n".join(blobs)
    match = AGENT_ID_RE.search(text)
    return match.group(0) if match else None


def _ensure_domain(board: Dict[str, Any], domain: str) -> Dict[str, Any]:
    domains: Dict[str, Any] = (board.get("org") or {}).setdefault("domains", {})
    node = domains.get(domain)
    if not node:
        node = {"label": domain, "status": "running", "l1": {}, "workers": []}
        domains[domain] = node
    node.setdefault("workers", [])
    node.setdefault("l1", {})
    return node


def attach_spawn(payload: Dict[str, Any], cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    session_id = session_id_of(payload)
    board = load_board(session_id, cwd or payload.get("cwd"))
    if not board or not board.get("active"):
        return board
    pending: List[Dict[str, Any]] = list(board.get("pending_spawns") or [])
    if not pending:
        return board
    spawn = pending.pop(0)
    board["pending_spawns"] = pending
    domain = slug_domain(str(spawn.get("domain") or infer_domain(payload, board)))
    node = _ensure_domain(board, domain)
    agent_id = _extract_agent_id(payload)
    kind = spawn.get("kind")
    if kind == "l1":
        node["l1"] = {
            "agent_id": agent_id,
            "status": "running",
            "subagent_type": spawn.get("subagent_type"),
            "description": spawn.get("description"),
        }
        node["status"] = "running"
        _append_event(board, "l0", "progress", f"spawned L1 for {domain}", domain)
    elif kind == "l2":
        workers = list(node.get("workers") or [])
        workers.append(
            {
                "agent_id": agent_id,
                "status": "running",
                "label": spawn.get("description") or "worker",
                "subagent_type": spawn.get("subagent_type"),
            }
        )
        node["workers"] = workers
        _append_event(board, f"l1:{domain}", "progress", f"spawned L2 {spawn.get('description') or ''}".strip(), domain)
    save_board(board, cwd or payload.get("cwd"))
    return board


def report(
    session_id: str,
    from_role: str,
    etype: str,
    summary: str,
    domain: Optional[str] = None,
    evidence: Optional[Iterable[str]] = None,
    agent_id: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    if etype not in ENVELOPE_TYPES:
        raise ValueError(f"envelope type must be one of {ENVELOPE_TYPES}")
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    domain_slug = slug_domain(domain) if domain else None
    evidence_list = [str(x)[:300] for x in (evidence or [])][:12]
    _append_event(board, from_role, etype, summary, domain_slug, evidence_list)
    if domain_slug:
        node = _ensure_domain(board, domain_slug)
        if from_role.startswith("l2") or from_role.startswith("worker"):
            for worker in node.get("workers") or []:
                if agent_id and worker.get("agent_id") == agent_id:
                    worker["status"] = "done" if etype == "done" else etype
                    break
            else:
                if etype in ("blocked", "need_input", "escalate", "done"):
                    node["status"] = etype if etype != "done" else node.get("status")
        if from_role.startswith("l1") or from_role == f"l1:{domain_slug}":
            node["status"] = "done" if etype == "done" else etype
            if node.get("l1"):
                node["l1"]["status"] = node["status"]
        if etype == "done":
            workers = node.get("workers") or []
            if workers and all(w.get("status") == "done" for w in workers):
                node["status"] = "done"
    if etype == "done" and from_role in ("l0", "root"):
        board["org"]["l0"]["status"] = "done"
        board["active"] = False
    save_board(board, cwd)
    return board


def register_identity(
    session_id: str,
    role: str,
    domain: Optional[str],
    agent_id: str,
    label: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    if role == "l1":
        node = _ensure_domain(board, slug_domain(domain or "general"))
        node["l1"] = {
            **(node.get("l1") or {}),
            "agent_id": agent_id,
            "status": "running",
            "label": label or domain,
        }
    elif role == "l2":
        node = _ensure_domain(board, slug_domain(domain or "general"))
        workers = list(node.get("workers") or [])
        for worker in workers:
            if worker.get("agent_id") == agent_id:
                worker["label"] = label or worker.get("label")
                break
        else:
            workers.append({"agent_id": agent_id, "status": "running", "label": label or "worker"})
        node["workers"] = workers
    save_board(board, cwd)
    return board


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return _as_bool(value.get("answer"))
    text = str(value or "").strip().lower()
    return text in ("true", "1", "yes")


def _reason_answer(value: Any, default: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return {
            "reason": str(value.get("reason") or "")[:1000],
            "answer": value.get("answer", default),
        }
    return {"reason": "", "answer": value if value is not None else default}


def set_task_ledger(
    session_id: str,
    facts: Optional[Dict[str, Any]] = None,
    facts_text: Optional[str] = None,
    plan: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    ledger = board.setdefault("task_ledger", empty_task_ledger())
    if facts:
        slot = ledger.setdefault("facts", {})
        for key in ("given", "look_up", "derive", "guesses"):
            if key in facts and facts[key] is not None:
                slot[key] = str(facts[key])[:4000]
    if facts_text is not None:
        ledger["facts_text"] = str(facts_text)[:8000]
    if plan is not None:
        ledger["plan"] = str(plan)[:8000]
    ledger["updated_at"] = _now()
    _append_event(board, "l0", "progress", "updated task ledger", None)
    save_board(board, cwd)
    return board


def record_progress(
    session_id: str,
    is_request_satisfied: Any,
    is_in_loop: Any,
    is_progress_being_made: Any,
    next_speaker: Any,
    instruction_or_question: Any,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    limits = board.get("limits") or {}
    max_stalls = int(limits.get("max_stalls") or MAX_STALLS)
    max_rounds = int(limits.get("max_rounds") or MAX_ROUNDS)
    progress = board.setdefault("progress", empty_progress())
    progress["n_rounds"] = int(progress.get("n_rounds") or 0) + 1

    satisfied = _reason_answer(is_request_satisfied, False)
    looping = _reason_answer(is_in_loop, False)
    moving = _reason_answer(is_progress_being_made, True)
    speaker = _reason_answer(next_speaker, "")
    instruction = _reason_answer(instruction_or_question, "")
    satisfied["answer"] = _as_bool(satisfied["answer"])
    looping["answer"] = _as_bool(looping["answer"])
    moving["answer"] = _as_bool(moving["answer"])
    speaker["answer"] = str(speaker.get("answer") or "")
    instruction["answer"] = str(instruction.get("answer") or "")

    stalled = (not moving["answer"]) or looping["answer"]
    if stalled:
        progress["n_stalls"] = int(progress.get("n_stalls") or 0) + 1
    else:
        progress["n_stalls"] = max(0, int(progress.get("n_stalls") or 0) - 1)

    action = "continue"
    if satisfied["answer"]:
        action = "complete"
        board["org"]["l0"]["status"] = "done"
        board["active"] = False
    elif progress["n_rounds"] >= max_rounds:
        action = "max_rounds"
    elif progress["n_stalls"] >= max_stalls:
        action = "replan"

    entry = {
        "ts": _now(),
        "is_request_satisfied": satisfied,
        "is_in_loop": looping,
        "is_progress_being_made": moving,
        "next_speaker": speaker,
        "instruction_or_question": instruction,
        "n_rounds": progress["n_rounds"],
        "n_stalls": progress["n_stalls"],
        "action": action,
    }
    progress["last"] = entry
    progress["action"] = action
    _append_event(
        board,
        "l0",
        "done" if action == "complete" else ("escalate" if action in ("replan", "max_rounds") else "progress"),
        f"progress action={action} stalls={progress['n_stalls']} next={speaker['answer'] or '-'}",
        None,
    )
    save_board(board, cwd)
    return board


def replan(
    session_id: str,
    facts_text: Optional[str] = None,
    plan: Optional[str] = None,
    reason: str = "stall",
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    progress = board.setdefault("progress", empty_progress())
    progress["n_stalls"] = 0
    progress["replan_count"] = int(progress.get("replan_count") or 0) + 1
    progress["action"] = "continue"
    terminal = frozenset({"done", "stale", "stopped"})
    domains = ((board.get("org") or {}).get("domains") or {})
    for node in domains.values():
        if str(node.get("status") or "running") not in terminal:
            node["status"] = "stale"
        l1 = node.get("l1") or {}
        if l1 and str(l1.get("status") or "running") not in terminal:
            l1["status"] = "stale"
            node["l1"] = l1
        for worker in node.get("workers") or []:
            if str(worker.get("status") or "running") not in terminal:
                worker["status"] = "stale"
    board["pending_spawns"] = []
    ledger = board.setdefault("task_ledger", empty_task_ledger())
    if facts_text is not None:
        ledger["facts_text"] = str(facts_text)[:8000]
    if plan is not None:
        ledger["plan"] = str(plan)[:8000]
    if facts_text is not None or plan is not None:
        ledger["updated_at"] = _now()
    _append_event(board, "l0", "escalate", f"replan ({reason}): mark live agents stale, spawn fresh briefs", None)
    save_board(board, cwd)
    return board


def forward_envelope(
    session_id: str,
    source: str,
    verbatim: str,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    board = load_board(session_id, cwd)
    if not board:
        raise FileNotFoundError("no hierarchical-supervisor board; run /hs first")
    forwarded = list(board.get("forwarded") or [])
    forwarded.append(
        {
            "ts": _now(),
            "source": source,
            "verbatim": verbatim[:8000],
        }
    )
    board["forwarded"] = forwarded[-12:]
    _append_event(board, source, "progress", "forwarded envelope verbatim", None)
    save_board(board, cwd)
    return board


def format_status(board: Optional[Dict[str, Any]]) -> str:
    if not board:
        return "HS board: none. Invoke /hs <task> to start."
    state = "ACTIVE" if board.get("active") else "STOPPED"
    limits = board.get("limits") or {}
    progress = board.get("progress") or {}
    ledger = board.get("task_ledger") or {}
    last = progress.get("last") or {}
    lines = [
        f"HS {state}  session={board.get('session_id')}  goal={board.get('goal') or '(none)'}",
        (
            f"limits: L1≤{limits.get('max_l1', MAX_L1)}  L2/domain≤{limits.get('max_l2_per_l1', MAX_L2_PER_L1)}  "
            f"depth≤2  stalls≤{limits.get('max_stalls', MAX_STALLS)}  rounds≤{limits.get('max_rounds', MAX_ROUNDS)}"
        ),
        (
            f"progress: rounds={progress.get('n_rounds', 0)} stalls={progress.get('n_stalls', 0)} "
            f"replans={progress.get('replan_count', 0)} action={progress.get('action') or 'continue'}"
        ),
    ]
    if ledger.get("plan"):
        lines.append("plan: " + str(ledger.get("plan")).splitlines()[0][:160])
    if last:
        nxt = ((last.get("next_speaker") or {}).get("answer")) or "-"
        lines.append(f"last next_speaker={nxt}")
    domains = ((board.get("org") or {}).get("domains") or {})
    if not domains:
        lines.append("org: L0 only (no domain managers yet)")
    for name, node in domains.items():
        l1 = (node.get("l1") or {}).get("agent_id") or "?"
        workers = node.get("workers") or []
        wtxt = ", ".join(f"{w.get('label') or 'w'}={w.get('status')}" for w in workers) or "no workers"
        lines.append(f"- {name}: {node.get('status')}  l1={l1}  workers[{len(workers)}]: {wtxt}")
    events = board.get("events") or []
    if events:
        lines.append("recent:")
        for ev in events[-6:]:
            lines.append(f"  [{ev.get('ts')}] {ev.get('from')} {ev.get('type')}: {ev.get('summary')}")
    return "\n".join(lines)


def protocol_card(board: Optional[Dict[str, Any]] = None) -> str:
    status = format_status(board)
    return (
        "HIERARCHICAL SUPERVISOR is active. You are L0 unless a subagent prompt says otherwise.\n"
        "Tree: L0 (you) -> L1 hs-manager per domain -> L2 hs-worker. Depth 2 max. No skipping, no sideways chat.\n"
        "Spawn: L0 only hs-manager (Explore allowed). L1 only hs-worker. L2 never Agent.\n"
        "Every L1/L2 brief MUST include `HS-DOMAIN:`, `GOAL:`, `DONE WHEN:` — hook denies incomplete briefs.\n"
        "Start with hs_ledger (facts+plan). Each L0/L1 step: hs_progress JSON. action=replan → mark stale, spawn NEW agents, do not SendMessage a stale worker.\n"
        "Mail: progress | need_input | blocked | done | escalate. Prefer hs_forward to pass an L1 envelope to the human verbatim.\n"
        "Browser / desktop stay at L0. Escalate to the human only for irreversible, security, or missing auth.\n"
        f"{status}"
    )


def hook_cwd(payload: Dict[str, Any]) -> Optional[str]:
    return _norm(payload.get("cwd") or payload.get("workingDirectory")) or None
