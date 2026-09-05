#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib.hs_board import (  # noqa: E402
    evaluate_agent_spawn,
    extract_domain,
    start_run,
    report,
    spawn_kind,
    caller_kind,
    record_progress,
    replan,
    set_task_ledger,
    missing_brief_fields,
    note_pending_spawn,
)


class HsBoardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hs-test-"))
        os.environ["ZCODE_PROJECT_DIR"] = str(self.tmp)
        os.environ["ZCODE_PLUGIN_DATA"] = str(self.tmp / "plugindata")
        self.session = "sess_test"
        start_run(self.session, "login tests and docs", cwd=str(self.tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _payload(self, **kwargs):
        base = {
            "session_id": self.session,
            "cwd": str(self.tmp),
            "tool_name": "Agent",
            "agent_type": "zcode",
            "tool_input": {
                "subagent_type": "hs-manager",
                "description": "test domain",
                "prompt": "HS-DOMAIN: test\nGOAL: write tests\nDONE WHEN: suite green",
            },
        }
        base.update(kwargs)
        if "tool_input" in kwargs:
            base["tool_input"] = kwargs["tool_input"]
        return base

    def test_domain_extract(self):
        self.assertEqual(extract_domain("HS-DOMAIN: backend"), "backend")

    def test_spawn_kind(self):
        self.assertEqual(spawn_kind("hs-manager"), "l1")
        self.assertEqual(spawn_kind("hierarchical-supervisor:hs-worker"), "l2")
        self.assertEqual(spawn_kind("Explore"), "explore")
        self.assertEqual(spawn_kind("general-purpose"), "other")

    def test_caller_kind(self):
        self.assertEqual(caller_kind({"agent_type": "zcode-hs-manager"}), "l1")
        self.assertEqual(caller_kind({"agent_type": "zcode-hs-worker"}), "l2")
        self.assertEqual(caller_kind({"agent_type": "zcode"}), "l0")

    def test_l0_can_spawn_manager(self):
        d = evaluate_agent_spawn(self._payload(), cwd=str(self.tmp))
        self.assertTrue(d["allow"], d)

    def test_l0_cannot_spawn_worker(self):
        d = evaluate_agent_spawn(
            self._payload(
                tool_input={
                    "subagent_type": "hs-worker",
                    "prompt": "HS-DOMAIN: test\nGOAL: write tests\nDONE WHEN: suite green",
                }
            ),
            cwd=str(self.tmp),
        )
        self.assertFalse(d["allow"], d)
        self.assertIn("cannot skip L1", d["reason"])

    def test_l2_cannot_spawn(self):
        d = evaluate_agent_spawn(
            self._payload(agent_type="zcode-hs-worker"),
            cwd=str(self.tmp),
        )
        self.assertFalse(d["allow"], d)

    def test_l1_can_spawn_worker(self):
        d = evaluate_agent_spawn(
            self._payload(
                agent_type="zcode-hs-manager",
                tool_input={
                    "subagent_type": "hs-worker",
                    "prompt": "HS-DOMAIN: test\nGOAL: one file\nDONE WHEN: file exists",
                },
            ),
            cwd=str(self.tmp),
        )
        self.assertTrue(d["allow"], d)

    def test_l1_cannot_spawn_manager(self):
        d = evaluate_agent_spawn(
            self._payload(agent_type="zcode-hs-manager"),
            cwd=str(self.tmp),
        )
        self.assertFalse(d["allow"], d)

    def test_l1_fanout_cap(self):
        for i in range(5):
            d = evaluate_agent_spawn(
                self._payload(
                    agent_type="zcode-hs-manager",
                    tool_input={
                        "subagent_type": "hs-worker",
                        "description": f"w{i}",
                        "prompt": "HS-DOMAIN: test\nGOAL: slice\nDONE WHEN: done",
                    },
                ),
                cwd=str(self.tmp),
            )
            self.assertTrue(d["allow"], d)
            note_pending_spawn(
                self._payload(
                    agent_type="zcode-hs-manager",
                    tool_input={
                        "subagent_type": "hs-worker",
                        "description": f"w{i}",
                        "prompt": "HS-DOMAIN: test\nGOAL: slice\nDONE WHEN: done",
                    },
                ),
                d,
                cwd=str(self.tmp),
            )
        d = evaluate_agent_spawn(
            self._payload(
                agent_type="zcode-hs-manager",
                tool_input={
                    "subagent_type": "hs-worker",
                    "prompt": "HS-DOMAIN: test\nGOAL: extra\nDONE WHEN: done",
                },
            ),
            cwd=str(self.tmp),
        )
        self.assertFalse(d["allow"], d)

    def test_report_and_board_file(self):
        board = report(
            self.session,
            from_role="l1:test",
            etype="progress",
            summary="workers running",
            domain="test",
            cwd=str(self.tmp),
        )
        path = self.tmp / ".zcode" / "hs" / "board.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["events"][-1]["type"], "progress")
        self.assertTrue(board["active"])

    def test_incomplete_brief_denied(self):
        self.assertEqual(missing_brief_fields("hello"), ["HS-DOMAIN", "GOAL", "DONE WHEN"])
        d = evaluate_agent_spawn(
            self._payload(tool_input={"subagent_type": "hs-manager", "prompt": "please help"}),
            cwd=str(self.tmp),
        )
        self.assertFalse(d["allow"], d)
        self.assertIn("incomplete", d["reason"])

    def test_progress_stalls_then_replan(self):
        for i in range(3):
            board = record_progress(
                self.session,
                is_request_satisfied={"reason": "not done", "answer": False},
                is_in_loop={"reason": "same ask", "answer": True},
                is_progress_being_made={"reason": "stuck", "answer": False},
                next_speaker={"reason": "retry", "answer": "hs-manager:test"},
                instruction_or_question={"reason": "retry", "answer": "try again"},
                cwd=str(self.tmp),
            )
        self.assertEqual(board["progress"]["action"], "replan")
        self.assertGreaterEqual(board["progress"]["n_stalls"], 3)

        set_task_ledger(self.session, plan="- retry with tighter domain", cwd=str(self.tmp))
        report(self.session, "l1:test", "progress", "running", domain="test", cwd=str(self.tmp))
        board = replan(self.session, plan="- new plan", reason="stalls", cwd=str(self.tmp))
        self.assertEqual(board["org"]["domains"]["test"]["status"], "stale")
        self.assertEqual(board["progress"]["n_stalls"], 0)
        self.assertEqual(board["task_ledger"]["plan"], "- new plan")

    def test_progress_complete_stops_run(self):
        board = record_progress(
            self.session,
            is_request_satisfied={"reason": "shipped", "answer": True},
            is_in_loop={"reason": "no", "answer": False},
            is_progress_being_made={"reason": "yes", "answer": True},
            next_speaker={"reason": "none", "answer": ""},
            instruction_or_question={"reason": "none", "answer": ""},
            cwd=str(self.tmp),
        )
        self.assertEqual(board["progress"]["action"], "complete")
        self.assertFalse(board["active"])


if __name__ == "__main__":
    unittest.main()
