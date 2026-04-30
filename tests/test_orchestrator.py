from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    "orchestrator.py",
    "browser_verify.py",
    "ralph.sh",
    "README.md",
    "CLAUDE.md",
    "prompt.md",
    "prd.json.example",
]
SOURCE_DIRS = ["schemas", "skills", ".claude-plugin", "flowchart", "docs"]


@dataclass
class ToolCase:
    root: Path
    stub_bin: Path
    target_repo: Path


class OrchestratorIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_case(self) -> ToolCase:
        case_root = Path(tempfile.mkdtemp(dir=self.temp_dir.name))
        tool_root = case_root / "tool"
        tool_root.mkdir(parents=True, exist_ok=True)
        for relative in SOURCE_FILES:
            shutil.copy2(SOURCE_ROOT / relative, tool_root / relative)
        for relative in SOURCE_DIRS:
            shutil.copytree(SOURCE_ROOT / relative, tool_root / relative)
        (tool_root / "ralph.sh").chmod(0o755)
        (tool_root / "browser_verify.py").chmod(0o755)

        stub_bin = case_root / "stub-bin"
        stub_bin.mkdir(parents=True, exist_ok=True)
        target_repo = case_root / "target-repo"
        target_repo.mkdir(parents=True, exist_ok=True)
        self._write_stub_binaries(stub_bin)
        return ToolCase(root=tool_root, stub_bin=stub_bin, target_repo=target_repo)

    def _write_stub_binaries(self, stub_bin: Path) -> None:
        codex_script = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import pathlib
            import sys

            args = sys.argv[1:]
            out_path = pathlib.Path(args[args.index("-o") + 1])
            prompt = sys.stdin.read()
            prompt_log = os.environ.get("STUB_CODEX_PROMPT_LOG")
            if prompt_log:
                with open(prompt_log, "a", encoding="utf-8") as handle:
                    handle.write(prompt)

            scenario = os.environ.get("STUB_CODEX_SCENARIO", "success")

            def write_payload(payload):
                if isinstance(payload, str):
                    out_path.write_text(payload, encoding="utf-8")
                else:
                    out_path.write_text(json.dumps(payload), encoding="utf-8")

            if "planning layer" in prompt:
                if scenario == "plan_duplicate":
                    write_payload({
                        "project_name": "demo",
                        "stories": [
                            {
                                "id": "S1",
                                "title": "dup one",
                                "objective": "one",
                                "acceptance_criteria": ["a"],
                                "dependencies": [],
                                "suggested_tests": ["python3 -c \\"print(1)\\""]
                            },
                            {
                                "id": "S1",
                                "title": "dup two",
                                "objective": "two",
                                "acceptance_criteria": ["b"],
                                "dependencies": [],
                                "suggested_tests": ["python3 -c \\"print(2)\\""]
                            }
                        ]
                    })
                elif scenario == "plan_cycle":
                    write_payload({
                        "project_name": "demo",
                        "stories": [
                            {
                                "id": "S1",
                                "title": "one",
                                "objective": "one",
                                "acceptance_criteria": ["a"],
                                "dependencies": ["S2"],
                                "suggested_tests": ["python3 -c \\"print(1)\\""]
                            },
                            {
                                "id": "S2",
                                "title": "two",
                                "objective": "two",
                                "acceptance_criteria": ["b"],
                                "dependencies": ["S1"],
                                "suggested_tests": ["python3 -c \\"print(2)\\""]
                            }
                        ]
                    })
                elif scenario == "plan_missing_dep":
                    write_payload({
                        "project_name": "demo",
                        "stories": [
                            {
                                "id": "S1",
                                "title": "one",
                                "objective": "one",
                                "acceptance_criteria": ["a"],
                                "dependencies": ["S9"],
                                "suggested_tests": ["python3 -c \\"print(1)\\""]
                            }
                        ]
                    })
                else:
                    write_payload({
                        "project_name": "demo",
                        "stories": [
                            {
                                "id": "S1",
                                "title": "Make a change",
                                "objective": "touch README",
                                "acceptance_criteria": ["README updated", "tests pass"],
                                "dependencies": [],
                                "suggested_tests": ["python3 -c \\"print('ok')\\""]
                            }
                        ]
                    })
            elif "review layer" in prompt:
                if scenario == "bad_review_json":
                    write_payload("{")
                elif scenario == "review_incomplete":
                    write_payload({
                        "complete": False,
                        "reason": "Acceptance criteria were not met.",
                        "progress_entry": "S1 incomplete.",
                        "remaining_work": ["finish the change"]
                    })
                else:
                    write_payload({
                        "complete": True,
                        "reason": "Evidence supports completing the story.",
                        "progress_entry": "S1 completed cleanly.",
                        "remaining_work": []
                    })
            else:
                if scenario == "bad_brief_json":
                    write_payload("{")
                else:
                    hints = ["browser"] if os.environ.get("STUB_CODEX_BROWSER_HINT") == "1" else []
                    write_payload({
                        "story_id": "S1",
                        "title": "Imported story",
                        "goal": "Update the repo with a tiny edit.",
                        "constraints": ["touch README only", "do not edit AGENTS.md unless needed"],
                        "acceptance_criteria": ["README updated", "tests pass"],
                        "test_commands": ["python3 -c \\"print('ok')\\""],
                        "verification_hints": hints,
                        "claude_prompt": "Append one line to README.md in the current repo. If AGENTS.md exists and no durable gotcha is found, do not edit it. Return the required JSON schema."
                    })
            print("stub codex")
            """
        )
        claude_script = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import pathlib
            import sys

            scenario = os.environ.get("STUB_CLAUDE_SCENARIO", "success")
            if scenario == "bad_json":
                print("{")
                sys.exit(0)

            repo = pathlib.Path.cwd()
            readme = repo / "README.md"
            if readme.exists():
                readme.write_text(readme.read_text(encoding="utf-8") + "\\nworker touched\\n", encoding="utf-8")
            else:
                readme.write_text("worker touched\\n", encoding="utf-8")

            payload = {
                "structured_output": {
                    "status": "blocked" if scenario == "blocked" else "success",
                    "summary": "worker made a tiny change",
                    "changed_files": ["README.md"],
                    "tests_run": [],
                    "blockers": ["blocked by test"] if scenario == "blocked" else []
                }
            }
            print(json.dumps(payload))
            """
        )
        for name, script in {"codex": codex_script, "claude": claude_script}.items():
            path = stub_bin / name
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)

    def _env(self, case: ToolCase, **overrides: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{case.stub_bin}:{env['PATH']}"
        env.update(overrides)
        return env

    def _run_runtime(
        self,
        case: ToolCase,
        *args: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(case.root / "orchestrator.py"), *args],
            cwd=str(cwd or case.root),
            env=env or self._env(case),
            capture_output=True,
            text=True,
        )

    def _run_facade(
        self,
        case: ToolCase,
        *args: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(case.root / "ralph.sh"), *args],
            cwd=str(cwd or case.root),
            env=env or self._env(case),
            capture_output=True,
            text=True,
        )

    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )

    def _init_git_repo(self, repo: Path) -> None:
        self._git(repo, "init", "-b", "main")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test User")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-m", "initial")

    def _write_import_prd(
        self,
        case: ToolCase,
        *,
        branch_name: str = "feature/demo",
        title: str = "Update README",
        description: str = "Append a worker line to README.md",
        acceptance_criteria: list[str] | None = None,
        passes: bool = False,
    ) -> Path:
        path = case.root / f"{branch_name.replace('/', '_')}.json"
        payload = {
            "branchName": branch_name,
            "userStories": [
                {
                    "id": "S1",
                    "title": title,
                    "description": description,
                    "acceptance_criteria": acceptance_criteria or ["README updated", "tests pass"],
                    "passes": passes,
                }
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _read_public_prd(self, case: ToolCase) -> dict[str, object]:
        return json.loads((case.root / "prd.json").read_text(encoding="utf-8"))

    def _read_internal_state(self, case: ToolCase) -> dict[str, object]:
        return json.loads((case.root / ".codex-ralph" / "state.json").read_text(encoding="utf-8"))

    def _read_config(self, case: ToolCase) -> dict[str, object]:
        return json.loads((case.root / ".codex-ralph" / "config.json").read_text(encoding="utf-8"))

    def test_source_repo_layout_matches_expected(self) -> None:
        expected_paths = [
            "ralph.sh",
            "prompt.md",
            "CLAUDE.md",
            "prd.json",
            "progress.txt",
            "prd.json.example",
            "skills/README.md",
            ".claude-plugin/plugin.json",
            "flowchart/loop.mmd",
            "browser_verify.py",
        ]
        for relative in expected_paths:
            with self.subTest(path=relative):
                self.assertTrue((SOURCE_ROOT / relative).exists(), relative)

        readme = (SOURCE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Codex** as planner and reviewer", readme)
        self.assertIn("Amp is intentionally unsupported", readme)

    def test_ralph_sh_rejects_amp(self) -> None:
        case = self._make_case()
        result = self._run_facade(case, "--tool", "amp", "doctor")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Amp is not supported", result.stderr)
        self.assertIn("Use --tool claude", result.stderr)

    def test_init_requires_git_by_default(self) -> None:
        case = self._make_case()
        result = self._run_facade(case, "init", "--repo", str(case.target_repo), "--goal", "demo goal")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-non-git", result.stderr)
        self.assertFalse((case.root / ".codex-ralph" / "config.json").exists())

    def test_ralph_sh_init_uses_root_prompt_and_writes_public_private_state(self) -> None:
        case = self._make_case()
        result = self._run_facade(case, "init", "--repo", str(case.target_repo), "--allow-non-git")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        public_prd = self._read_public_prd(case)
        self.assertEqual(set(public_prd), {"projectName", "branchName", "userStories"})
        self.assertEqual(set(public_prd["userStories"][0]), {"id", "title", "description", "acceptance_criteria", "dependencies", "suggested_tests", "passes"})
        self.assertFalse(public_prd["userStories"][0]["passes"])

        config = self._read_config(case)
        state = self._read_internal_state(case)
        self.assertEqual(Path(config["repo_path"]), case.target_repo.resolve())
        self.assertFalse(config["require_git"])
        self.assertEqual(state["source_format"], "generated")
        self.assertEqual(state["stories"][0]["status"], "pending")
        self.assertIn("attempt_count", state["stories"][0])
        self.assertTrue((case.root / "progress.txt").exists())
        self.assertIn("CityGenius 订阅与支付接入测试", (case.root / "prompt.md").read_text(encoding="utf-8"))

    def test_plan_validation_rejects_duplicate_cycle_and_missing_dependency(self) -> None:
        for scenario, expected in (
            ("plan_duplicate", "Duplicate story IDs"),
            ("plan_cycle", "Cycle detected"),
            ("plan_missing_dep", "missing dependency"),
        ):
            with self.subTest(scenario=scenario):
                case = self._make_case()
                env = self._env(case, STUB_CODEX_SCENARIO=scenario)
                result = self._run_runtime(
                    case,
                    "init",
                    "--repo",
                    str(case.target_repo),
                    "--goal",
                    "demo",
                    "--allow-non-git",
                    env=env,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertFalse((case.root / ".codex-ralph" / "config.json").exists())

    def test_imported_ralph_json_archives_branch_state_under_hidden_archive(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        alpha = self._write_import_prd(case, branch_name="feature/alpha")
        beta = self._write_import_prd(case, branch_name="feature/beta")

        first = self._run_facade(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(alpha))
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        second = self._run_facade(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(beta))
        self.assertEqual(second.returncode, 0, msg=second.stderr)

        state = self._read_internal_state(case)
        self.assertEqual(state["branch_name"], "feature/beta")
        self.assertEqual(self._read_public_prd(case)["branchName"], "feature/beta")

        archives = list((case.root / ".codex-ralph" / "archive").glob("*feature-alpha"))
        self.assertEqual(len(archives), 1)
        archived_dir = archives[0]
        archived_state = json.loads((archived_dir / "state.json").read_text(encoding="utf-8"))
        archived_public = json.loads((archived_dir / "prd.json").read_text(encoding="utf-8"))
        self.assertEqual(archived_state["branch_name"], "feature/alpha")
        self.assertEqual(archived_public["branchName"], "feature/alpha")

    def test_legacy_state_migrates_to_hidden_runtime(self) -> None:
        case = self._make_case()
        (case.root / "prompt.md").unlink()
        legacy_dir = case.root / "state"
        legacy_runs = legacy_dir / "runs"
        legacy_runs.mkdir(parents=True, exist_ok=True)
        legacy_config = {
            "repo_path": str(case.target_repo),
            "planner_model": None,
            "reviewer_model": None,
            "claude_model": None,
            "default_test_commands": ["python3 -c \"print('ok')\""],
            "require_git": False,
        }
        legacy_prd = {
            "project_name": "legacy-demo",
            "branch_name": "feature/legacy",
            "source_format": "canonical_v1",
            "require_git": False,
            "stories": [
                {
                    "id": "S1",
                    "title": "Legacy Story",
                    "objective": "Keep the old state readable",
                    "acceptance_criteria": ["state migrated"],
                    "dependencies": [],
                    "suggested_tests": ["python3 -c \"print('ok')\""],
                    "status": "pending",
                    "attempt_count": 0,
                    "last_run_id": None,
                    "remaining_work": [],
                    "last_review_reason": "",
                    "verification_hints": [],
                }
            ],
        }
        (legacy_dir / "config.json").write_text(json.dumps(legacy_config), encoding="utf-8")
        (legacy_dir / "prd.json").write_text(json.dumps(legacy_prd), encoding="utf-8")
        (legacy_dir / "progress.txt").write_text("legacy progress\n", encoding="utf-8")
        (legacy_dir / "prd.md").write_text("# legacy prompt\n", encoding="utf-8")
        (legacy_runs / "old.json").write_text("{}", encoding="utf-8")

        result = self._run_runtime(case, "status")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(legacy_dir.exists())
        self.assertEqual(self._read_internal_state(case)["source_format"], "canonical_v1")
        self.assertEqual(self._read_public_prd(case)["branchName"], "feature/legacy")
        self.assertEqual((case.root / "progress.txt").read_text(encoding="utf-8"), "legacy progress\n")
        self.assertEqual((case.root / "prompt.md").read_text(encoding="utf-8"), "# legacy prompt\n")
        archived = list((case.root / ".codex-ralph" / "archive" / "legacy-state").glob("*/config.json"))
        self.assertEqual(len(archived), 1)

    def test_run_via_ralph_sh_claude_creates_branch_commit_and_consistent_run_artifacts(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        prd = self._write_import_prd(case)

        init = self._run_facade(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd))
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        run = self._run_facade(case, "--tool", "claude", "run", "--max-steps", "1")
        self.assertEqual(run.returncode, 0, msg=run.stderr)

        public_prd = self._read_public_prd(case)
        state = self._read_internal_state(case)
        story = state["stories"][0]
        self.assertTrue(public_prd["userStories"][0]["passes"])
        self.assertEqual(story["status"], "passed")
        self.assertEqual(story["attempt_count"], 1)
        run_id = story["last_run_id"]
        self.assertTrue(run_id)

        run_files = sorted(path.name for path in (case.root / ".codex-ralph" / "runs").glob(f"{run_id}_S1_*"))
        self.assertEqual(run_files, [
            f"{run_id}_S1_brief.json",
            f"{run_id}_S1_brief_raw.json",
            f"{run_id}_S1_review.json",
            f"{run_id}_S1_review_raw.json",
            f"{run_id}_S1_tests.json",
            f"{run_id}_S1_worker.json",
            f"{run_id}_S1_worker_raw.json",
        ])

        branch = self._git(case.target_repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        subject = self._git(case.target_repo, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertEqual(branch, "feature/demo")
        self.assertEqual(subject, "ralph: S1 Update README")
        self.assertIn("committed as", (case.root / "progress.txt").read_text(encoding="utf-8"))

    def test_ralph_sh_run_auto_init_honors_explicit_repo(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)

        run = self._run_facade(case, "run", "--repo", str(case.target_repo), "--max-steps", "1", "--no-commit")
        self.assertEqual(run.returncode, 0, msg=run.stderr)

        config = self._read_config(case)
        state = self._read_internal_state(case)
        self.assertEqual(Path(config["repo_path"]), case.target_repo.resolve())
        self.assertEqual(state["stories"][0]["status"], "passed")
        self.assertIn("worker touched", (case.target_repo / "README.md").read_text(encoding="utf-8"))

    def test_retryable_runtime_failures_mark_story_failed(self) -> None:
        scenarios = [
            ("bad_brief_json", {}),
            ("success", {"STUB_CLAUDE_SCENARIO": "bad_json"}),
            ("bad_review_json", {}),
        ]
        for scenario, extra_env in scenarios:
            with self.subTest(scenario=scenario, extra_env=extra_env):
                case = self._make_case()
                self._init_git_repo(case.target_repo)
                prd = self._write_import_prd(case)
                env = self._env(case, STUB_CODEX_SCENARIO=scenario, **extra_env)

                init = self._run_runtime(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd), env=env)
                self.assertEqual(init.returncode, 0, msg=init.stderr)
                run = self._run_runtime(case, "run", "--max-steps", "1", env=env)
                self.assertEqual(run.returncode, 0, msg=run.stderr)

                state = self._read_internal_state(case)
                self.assertEqual(state["stories"][0]["status"], "failed")
                self.assertIn("failure", (case.root / "progress.txt").read_text(encoding="utf-8"))

    def test_ui_story_browser_verification_requires_real_result(self) -> None:
        pass_command = "python3 -c 'import json; print(json.dumps({\"status\": \"passed\", \"message\": \"browser ok\"}))'"
        fail_command = "python3 -c 'import json,sys; print(json.dumps({\"status\": \"failed\", \"message\": \"browser failed\"})); sys.exit(1)'"
        cases = [
            ("missing", None, "blocked"),
            ("passed", pass_command, "passed"),
            ("failed", fail_command, "blocked"),
        ]
        for label, browser_command, expected_status in cases:
            with self.subTest(browser=label):
                case = self._make_case()
                self._init_git_repo(case.target_repo)
                prd = self._write_import_prd(
                    case,
                    branch_name="feature/ui",
                    title="Update UI screen",
                    description="Adjust the browser-facing screen",
                    acceptance_criteria=["UI updated", "browser verification passes"],
                )
                init_args = ["init", "--repo", str(case.target_repo), "--import-prd-json", str(prd)]
                if browser_command:
                    init_args.extend(["--browser-verify-command", browser_command])
                init = self._run_runtime(case, *init_args)
                self.assertEqual(init.returncode, 0, msg=init.stderr)

                env = self._env(case, STUB_CODEX_BROWSER_HINT="1")
                run = self._run_runtime(case, "run", "--max-steps", "1", "--no-commit", env=env)
                self.assertEqual(run.returncode, 0, msg=run.stderr)

                state = self._read_internal_state(case)
                self.assertEqual(state["stories"][0]["status"], expected_status)
                tests_payload = json.loads(next((case.root / ".codex-ralph" / "runs").glob("*_S1_tests.json")).read_text(encoding="utf-8"))
                browser_result = tests_payload[-1]
                self.assertEqual(browser_result["kind"], "browser")
                self.assertEqual(browser_result["status"], label)

    def test_review_incomplete_blocks_story(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        prd = self._write_import_prd(case)
        env = self._env(case, STUB_CODEX_SCENARIO="review_incomplete")

        init = self._run_runtime(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd), env=env)
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        run = self._run_runtime(case, "run", "--max-steps", "1", env=env)
        self.assertEqual(run.returncode, 0, msg=run.stderr)

        state = self._read_internal_state(case)
        self.assertEqual(state["stories"][0]["status"], "blocked")
        self.assertIn("Acceptance criteria were not met.", state["stories"][0]["last_review_reason"])

    def test_lock_file_blocks_run(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        prd = self._write_import_prd(case)
        init = self._run_runtime(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd))
        self.assertEqual(init.returncode, 0, msg=init.stderr)

        lock_path = case.root / ".codex-ralph" / ".run.lock"
        lock_path.write_text("999999 stale\n", encoding="utf-8")
        result = self._run_runtime(case, "run", "--max-steps", "1")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(lock_path.exists())

        lock_path.write_text(f"{os.getpid()} active\n", encoding="utf-8")
        result = self._run_runtime(case, "run", "--max-steps", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Another run appears to be active", result.stderr)

    def test_load_plan_heals_orphan_running_story(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        prd = self._write_import_prd(case)
        init = self._run_runtime(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd))
        self.assertEqual(init.returncode, 0, msg=init.stderr)

        state_path = case.root / ".codex-ralph" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["stories"][0]["status"] = "running"
        state["stories"][0]["last_run_id"] = "run123"
        state["stories"][0]["remaining_work"] = []
        state["stories"][0]["last_review_reason"] = ""
        state_path.write_text(json.dumps(state), encoding="utf-8")

        status = self._run_runtime(case, "status")
        self.assertEqual(status.returncode, 0, msg=status.stderr)

        healed = self._read_internal_state(case)
        self.assertEqual(healed["stories"][0]["status"], "blocked")
        self.assertIn("Previous run exited before this story completed.", healed["stories"][0]["last_review_reason"])
        self.assertIn("Review repo state and rerun this story after resolving the interrupted attempt.", healed["stories"][0]["remaining_work"])

    def test_prompt_compaction_uses_recent_progress_only(self) -> None:
        case = self._make_case()
        self._init_git_repo(case.target_repo)
        prd = self._write_import_prd(case)
        init = self._run_runtime(case, "init", "--repo", str(case.target_repo), "--import-prd-json", str(prd))
        self.assertEqual(init.returncode, 0, msg=init.stderr)

        progress_path = case.root / "progress.txt"
        with progress_path.open("a", encoding="utf-8") as handle:
            for index in range(1, 21):
                handle.write(f"line-{index}\n")
        fake_raw = case.root / ".codex-ralph" / "runs" / "old_raw.json"
        fake_raw.write_text('{"stderr":"SHOULD_NOT_APPEAR"}', encoding="utf-8")

        prompt_log = case.root / "prompt.log"
        env = self._env(case, STUB_CODEX_PROMPT_LOG=str(prompt_log))
        result = self._run_runtime(case, "run", "--dry-run", env=env)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prompt_text = prompt_log.read_text(encoding="utf-8")
        self.assertIn('"line-20"', prompt_text)
        self.assertIn('"line-11"', prompt_text)
        self.assertNotIn('"line-10"', prompt_text)
        self.assertNotIn("SHOULD_NOT_APPEAR", prompt_text)

    def test_doctor_reports_runtime_health(self) -> None:
        case = self._make_case()
        browser_command = "python3 -c 'import json; print(json.dumps({\"status\": \"passed\", \"message\": \"browser ok\"}))'"
        init = self._run_runtime(
            case,
            "init",
            "--repo",
            str(case.target_repo),
            "--goal",
            "demo",
            "--allow-non-git",
            "--browser-verify-command",
            browser_command,
        )
        self.assertEqual(init.returncode, 0, msg=init.stderr)

        doctor = self._run_facade(case, "doctor")
        self.assertEqual(doctor.returncode, 0, msg=doctor.stderr)
        self.assertIn("repo_mode: non_git", doctor.stdout)
        self.assertIn("browser_verify_command:", doctor.stdout)
        self.assertIn("codex:", doctor.stdout)
        self.assertIn("claude:", doctor.stdout)
        self.assertIn("doctor: ok", doctor.stdout)


if __name__ == "__main__":
    unittest.main()
