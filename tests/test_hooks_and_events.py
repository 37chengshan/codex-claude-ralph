from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HooksAndEventsTests(unittest.TestCase):
    def test_hook_configs_resolve_expected_paths(self) -> None:
        for relative in ["hooks/settings.global.json", "hooks/settings.project.json"]:
            payload = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            hooks = payload["codex_claude_ralph"]["hooks"]
            self.assertIn("session_bootstrap", hooks)
            self.assertIn("worker_intercept", hooks)
            self.assertIn("progress_status", hooks)
            self.assertIn("doctor.sh", hooks["session_bootstrap"]["command"])
            self.assertIn("claude-worker-bridge.sh", hooks["worker_intercept"]["command"])
            self.assertIn("status --json", hooks["progress_status"]["command"])

    def test_events_append_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".codex-ralph").mkdir()
            (repo / ".codex-ralph" / "state.json").write_text(
                json.dumps(
                    {
                        "stage": "plan_gate",
                        "status": "passed",
                        "message": "approved",
                        "current_story": None,
                        "progress": {"completed": 0, "total": 1},
                        "stories": [
                            {
                                "id": "S1",
                                "title": "Demo",
                                "description": "Demo",
                                "acceptance_criteria": ["x"],
                                "suggested_tests": ["echo ok"],
                                "dependencies": [],
                                "status": "pending",
                                "attempt_count": 0,
                                "last_run_id": None,
                                "remaining_work": [],
                                "last_review_reason": ""
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (repo / ".codex-ralph" / "plan_score.json").write_text(
                json.dumps({"total": 90, "decision": "approved", "threshold": 85, "hard_blockers": []}),
                encoding="utf-8",
            )

            append = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runtime" / "scripts" / "ralph-events.py"),
                    "append",
                    "--repo",
                    str(repo),
                    "--stage",
                    "plan_gate",
                    "--status",
                    "passed",
                    "--message",
                    "approved",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(append.returncode, 0, append.stderr)
            status = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runtime" / "scripts" / "ralph-events.py"),
                    "status",
                    "--repo",
                    str(repo),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["stage"], "plan_gate")
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["progress"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
