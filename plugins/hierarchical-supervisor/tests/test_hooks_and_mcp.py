#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOKS = PLUGIN_ROOT / "hooks"
MCP = PLUGIN_ROOT / "mcp" / "server.py"


class HookAndMcpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hs-hook-"))
        self.env = os.environ.copy()
        self.env["ZCODE_PROJECT_DIR"] = str(self.tmp)
        self.env["ZCODE_PLUGIN_DATA"] = str(self.tmp / "plugindata")
        self.env["ZCODE_SESSION_ID"] = "sess_hook"
        start = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "hs_start",
                "arguments": {"goal": "demo", "session_id": "sess_hook"},
            },
        }
        self._mcp([{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}, start])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_hook(self, script: str, payload: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, str(HOOKS / script)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip() or "{}")

    def _frame(self, obj: dict) -> bytes:
        data = json.dumps(obj).encode("utf-8")
        return f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data

    def _parse_frames(self, raw: bytes):
        out = []
        buf = raw
        while buf:
            if buf.startswith(b"{") or buf.startswith(b"["):
                line, _, rest = buf.partition(b"\n")
                out.append(json.loads(line))
                buf = rest
                continue
            header, sep, rest = buf.partition(b"\r\n\r\n")
            if not sep:
                header, sep, rest = buf.partition(b"\n\n")
            if not sep:
                break
            length = 0
            for line in header.split(b"\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())
            body, buf = rest[:length], rest[length:]
            out.append(json.loads(body))
        return out

    def _mcp(self, messages):
        blob = b"".join(self._frame(m) for m in messages)
        proc = subprocess.run(
            [sys.executable, str(MCP)],
            input=blob,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        return self._parse_frames(proc.stdout)

    def test_initialize(self):
        lines = self._mcp([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}])
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "hierarchical-supervisor")

    def test_deny_l0_worker(self):
        out = self._run_hook(
            "pretooluse.py",
            {
                "session_id": "sess_hook",
                "cwd": str(self.tmp),
                "tool_name": "Agent",
                "agent_type": "zcode",
                "tool_input": {
                    "subagent_type": "hs-worker",
                    "prompt": "HS-DOMAIN: test\nGOAL: write tests\nDONE WHEN: suite green",
                },
            },
        )
        spec = out.get("hookSpecificOutput") or {}
        self.assertEqual(spec.get("permissionDecision"), "deny")

    def test_allow_l0_manager(self):
        out = self._run_hook(
            "pretooluse.py",
            {
                "session_id": "sess_hook",
                "cwd": str(self.tmp),
                "tool_name": "Agent",
                "agent_type": "zcode",
                "tool_input": {
                    "subagent_type": "hs-manager",
                    "description": "test mgr",
                    "prompt": "HS-DOMAIN: test\nGOAL: own the test domain\nDONE WHEN: suite green",
                },
            },
        )
        self.assertNotEqual((out.get("hookSpecificOutput") or {}).get("permissionDecision"), "deny")

    def test_deny_incomplete_brief(self):
        out = self._run_hook(
            "pretooluse.py",
            {
                "session_id": "sess_hook",
                "cwd": str(self.tmp),
                "tool_name": "Agent",
                "agent_type": "zcode",
                "tool_input": {"subagent_type": "hs-manager", "prompt": "go do tests"},
            },
        )
        spec = out.get("hookSpecificOutput") or {}
        self.assertEqual(spec.get("permissionDecision"), "deny")

    def test_progress_tool(self):
        lines = self._mcp(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "hs_ledger",
                        "arguments": {
                            "session_id": "sess_hook",
                            "plan": "- spawn test manager",
                            "facts": {"given": "login API exists"},
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "hs_progress",
                        "arguments": {
                            "session_id": "sess_hook",
                            "is_request_satisfied": {"reason": "just started", "answer": False},
                            "is_in_loop": {"reason": "no", "answer": False},
                            "is_progress_being_made": {"reason": "yes", "answer": True},
                            "next_speaker": {"reason": "need tests", "answer": "hs-manager:test"},
                            "instruction_or_question": {"reason": "go", "answer": "write tests"},
                        },
                    },
                },
            ]
        )
        last = json.loads(lines[-1]["result"]["content"][0]["text"])
        self.assertTrue(last["ok"])
        self.assertEqual(last["action"], "continue")


if __name__ == "__main__":
    unittest.main()
