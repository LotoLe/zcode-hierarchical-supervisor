#!/usr/bin/env python3
"""Stdio MCP server: org chart + postal board for Hierarchical Supervisor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import (  # noqa: E402
    ENVELOPE_TYPES,
    format_status,
    forward_envelope,
    load_board,
    record_progress,
    register_identity,
    replan,
    report,
    session_id_of,
    set_task_ledger,
    start_run,
    stop_run,
)


def _session(arguments: Dict[str, Any]) -> str:
    sid = str(arguments.get("session_id") or "").strip()
    return sid or session_id_of({})


def _cwd() -> Optional[str]:
    return os.environ.get("ZCODE_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR")


def _ok(text: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {"ok": True, "text": text}
    if extra:
        payload.update(extra)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]
    }


def _err(message: str) -> Dict[str, Any]:
    return {
        "isError": True,
        "content": [{"type": "text", "text": json.dumps({"ok": False, "error": message}, ensure_ascii=False)}],
    }


def handle_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _cwd()
    try:
        if name == "hs_start":
            goal = str(arguments.get("goal") or "").strip()
            if not goal:
                return _err("goal is required")
            board = start_run(_session(arguments), goal, cwd)
            return _ok(format_status(board), {"board": board})
        if name == "hs_status":
            board = load_board(_session(arguments), cwd)
            return _ok(format_status(board), {"board": board})
        if name == "hs_report":
            etype = str(arguments.get("type") or "").strip()
            summary = str(arguments.get("summary") or "").strip()
            if etype not in ENVELOPE_TYPES:
                return _err(f"type must be one of {list(ENVELOPE_TYPES)}")
            if not summary:
                return _err("summary is required")
            board = report(
                session_id=_session(arguments),
                from_role=str(arguments.get("from") or "unknown"),
                etype=etype,
                summary=summary,
                domain=arguments.get("domain"),
                evidence=arguments.get("evidence") or [],
                agent_id=arguments.get("agent_id"),
                cwd=cwd,
            )
            return _ok(format_status(board), {"board": board})
        if name == "hs_register":
            role = str(arguments.get("role") or "").strip()
            agent_id = str(arguments.get("agent_id") or "").strip()
            if role not in ("l1", "l2"):
                return _err("role must be l1 or l2")
            if not agent_id:
                return _err("agent_id is required")
            board = register_identity(
                session_id=_session(arguments),
                role=role,
                domain=arguments.get("domain"),
                agent_id=agent_id,
                label=arguments.get("label"),
                cwd=cwd,
            )
            return _ok(format_status(board), {"board": board})
        if name == "hs_stop":
            board = stop_run(_session(arguments), cwd, reason=str(arguments.get("reason") or "stopped"))
            return _ok(format_status(board), {"board": board})
        if name == "hs_ledger":
            facts = arguments.get("facts")
            if facts is not None and not isinstance(facts, dict):
                return _err("facts must be an object with given/look_up/derive/guesses")
            board = set_task_ledger(
                session_id=_session(arguments),
                facts=facts,
                facts_text=arguments.get("facts_text"),
                plan=arguments.get("plan"),
                cwd=cwd,
            )
            return _ok(format_status(board), {"board": board})
        if name == "hs_progress":
            board = record_progress(
                session_id=_session(arguments),
                is_request_satisfied=arguments.get("is_request_satisfied"),
                is_in_loop=arguments.get("is_in_loop"),
                is_progress_being_made=arguments.get("is_progress_being_made"),
                next_speaker=arguments.get("next_speaker"),
                instruction_or_question=arguments.get("instruction_or_question"),
                cwd=cwd,
            )
            action = ((board.get("progress") or {}).get("action")) or "continue"
            extra = {"board": board, "action": action}
            if action == "replan":
                extra["hint"] = (
                    "Stalls exceeded. Call hs_ledger with updated facts+plan, then hs_replan. "
                    "Do not SendMessage stale agents — spawn fresh hs-manager briefs."
                )
            if action == "max_rounds":
                extra["hint"] = "max_rounds reached. Synthesize what you have, escalate leftovers, hs_stop."
            if action == "complete":
                extra["hint"] = "Request marked satisfied. Forward remaining envelopes, then hs_stop."
            return _ok(format_status(board), extra)
        if name == "hs_replan":
            board = replan(
                session_id=_session(arguments),
                facts_text=arguments.get("facts_text"),
                plan=arguments.get("plan"),
                reason=str(arguments.get("reason") or "stall"),
                cwd=cwd,
            )
            return _ok(format_status(board), {"board": board, "action": "replan"})
        if name == "hs_forward":
            source = str(arguments.get("source") or "").strip()
            verbatim = str(arguments.get("verbatim") or "").strip()
            if not source or not verbatim:
                return _err("source and verbatim are required")
            board = forward_envelope(_session(arguments), source, verbatim, cwd)
            return _ok(verbatim, {"board": board, "forwarded": True})
        return _err(f"unknown tool {name}")
    except Exception as exc:
        return _err(str(exc))


TOOLS = [
    {
        "name": "hs_start",
        "description": "Start a Hierarchical Supervisor run and create the session board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "User task for this run"},
                "session_id": {"type": "string"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "hs_status",
        "description": "Read the org chart, worker status, and recent envelopes.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
        },
    },
    {
        "name": "hs_report",
        "description": "Post a postal envelope onto the board: progress, need_input, blocked, done, or escalate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from": {"type": "string", "description": "l0 | l1:<domain> | l2:<domain>"},
                "type": {"type": "string", "enum": list(ENVELOPE_TYPES)},
                "summary": {"type": "string"},
                "domain": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "agent_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["from", "type", "summary"],
        },
    },
    {
        "name": "hs_register",
        "description": "Register this agent onto the org chart after spawn.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": ["l1", "l2"]},
                "domain": {"type": "string"},
                "agent_id": {"type": "string"},
                "label": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["role", "agent_id"],
        },
    },
    {
        "name": "hs_stop",
        "description": "Deactivate Hierarchical Supervisor for this session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "hs_ledger",
        "description": "Write or update the Magentic-One-style Task Ledger: given/look_up/derive/guesses facts plus a short plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "object",
                    "properties": {
                        "given": {"type": "string"},
                        "look_up": {"type": "string"},
                        "derive": {"type": "string"},
                        "guesses": {"type": "string"},
                    },
                },
                "facts_text": {"type": "string"},
                "plan": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "hs_progress",
        "description": "Record one inner-loop Progress Ledger step. Required JSON: is_request_satisfied, is_in_loop, is_progress_being_made, next_speaker, instruction_or_question. Returns action continue|replan|complete|max_rounds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "is_request_satisfied": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}, "answer": {"type": "boolean"}},
                    "required": ["answer"],
                },
                "is_in_loop": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}, "answer": {"type": "boolean"}},
                    "required": ["answer"],
                },
                "is_progress_being_made": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}, "answer": {"type": "boolean"}},
                    "required": ["answer"],
                },
                "next_speaker": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}, "answer": {"type": "string"}},
                    "required": ["answer"],
                },
                "instruction_or_question": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}, "answer": {"type": "string"}},
                    "required": ["answer"],
                },
                "session_id": {"type": "string"},
            },
            "required": [
                "is_request_satisfied",
                "is_in_loop",
                "is_progress_being_made",
                "next_speaker",
                "instruction_or_question",
            ],
        },
    },
    {
        "name": "hs_replan",
        "description": "Outer-loop replan after stalls: update facts/plan, mark live L1/L2 stale, require fresh Agent spawns with new briefs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "facts_text": {"type": "string"},
                "plan": {"type": "string"},
                "reason": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "hs_forward",
        "description": "Pass an L1 envelope to the human verbatim (LangGraph forward_message). Do not rewrite evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "l1:<domain>"},
                "verbatim": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["source", "verbatim"],
        },
    },
]


def _write_message(obj: Dict[str, Any]) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + data)
    sys.stdout.buffer.flush()


def _read_message() -> Optional[Dict[str, Any]]:
    header_line = sys.stdin.buffer.readline()
    if not header_line:
        return None
    stripped = header_line.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return json.loads(header_line.decode("utf-8"))
    headers: Dict[str, str] = {}
    line = header_line
    while line not in (b"", b"\r\n", b"\n"):
        decoded = line.decode("ascii", errors="replace")
        key, _, value = decoded.partition(":")
        headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
        if not line:
            break
    length = int(headers.get("content-length") or 0)
    body = sys.stdin.buffer.read(length) if length else b""
    if not body:
        return None
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


def _reply(msg_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> None:
    body: Dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    _write_message(body)


def handle_message(msg: Dict[str, Any]) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        _reply(
            msg_id,
            {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hierarchical-supervisor", "version": "0.1.0"},
            },
        )
        return
    if method == "notifications/initialized":
        return
    if method == "tools/list":
        _reply(msg_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        _reply(msg_id, handle_tool(name, arguments))
        return
    if method == "ping":
        _reply(msg_id, {})
        return
    if msg_id is not None:
        _reply(msg_id, error={"code": -32601, "message": f"Unknown method {method}"})


def main() -> int:
    while True:
        try:
            msg = _read_message()
        except json.JSONDecodeError:
            continue
        if msg is None:
            return 0
        if isinstance(msg, dict):
            handle_message(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
