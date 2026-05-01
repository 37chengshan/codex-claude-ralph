from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkerAdapterTests(unittest.TestCase):
    def _stub_claude(self, bin_dir: Path, *, body: str, exit_code: int = 0, sleep_seconds: int = 0) -> None:
        script = textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import time
            import sys
            if {sleep_seconds}:
                time.sleep({sleep_seconds})
            print({body!r})
            sys.exit({exit_code})
            """
        )
        path = bin_dir / "claude"
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def _run_bridge(self, *, body: str, exit_code: int = 0, sleep_seconds: int = 0, timeout: int = 5) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_path = Path(tmp.name)
        repo = tmp_path / "repo"
        cwd = tmp_path / "cwd"
        bin_dir = tmp_path / "bin"
        repo.mkdir()
        cwd.mkdir()
        bin_dir.mkdir()
        (repo / ".codex-ralph" / "runs").mkdir(parents=True)
        self._stub_claude(bin_dir, body=body, exit_code=exit_code, sleep_seconds=sleep_seconds)
        output = repo / ".codex-ralph" / "runs" / "worker.json"
        raw_output = repo / ".codex-ralph" / "runs" / "worker_raw.json"
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "runtime" / "scripts" / "claude-worker-bridge.py"),
                "run",
                "--repo",
                str(repo),
                "--cwd",
                str(cwd),
                "--story-id",
                "S1",
                "--story-title",
                "Demo",
                "--output",
                str(output),
                "--raw-output",
                str(raw_output),
                "--timeout",
                str(timeout),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        return result, output, raw_output

    def test_success(self) -> None:
        result, output, _ = self._run_bridge(
            body=json.dumps(
                {
                    "structured_output": {
                        "status": "success",
                        "summary": "done",
                        "changed_files": ["README.md"],
                        "tests_run": [],
                        "blockers": [],
                    }
                }
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["structured_output"]["status"], "success")

    def test_blocked(self) -> None:
        result, output, _ = self._run_bridge(
            body=json.dumps(
                {
                    "structured_output": {
                        "status": "blocked",
                        "summary": "blocked",
                        "changed_files": [],
                        "tests_run": [],
                        "blockers": ["waiting"],
                    }
                }
            )
        )
        self.assertEqual(result.returncode, 6)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["structured_output"]["status"], "blocked")

    def test_invalid_json(self) -> None:
        result, output, _ = self._run_bridge(body="not json")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["structured_output"]["status"], "failed")
        self.assertIn("invalid_json", payload["structured_output"]["blockers"])

    def test_non_zero_exit(self) -> None:
        result, output, _ = self._run_bridge(
            body=json.dumps(
                {
                    "structured_output": {
                        "status": "failed",
                        "summary": "failed",
                        "changed_files": [],
                        "tests_run": [],
                        "blockers": ["non_zero_exit"],
                    }
                }
            ),
            exit_code=9,
        )
        self.assertEqual(result.returncode, 9)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["structured_output"]["status"], "failed")

    def test_timeout(self) -> None:
        result, output, raw_output = self._run_bridge(body="{}", sleep_seconds=2, timeout=1)
        self.assertEqual(result.returncode, 124)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["structured_output"]["status"], "failed")
        self.assertTrue(raw_output.exists())


if __name__ == "__main__":
    unittest.main()
