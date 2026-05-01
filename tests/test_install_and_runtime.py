from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_goal_spec(
    path: Path,
    *,
    confirmed: bool = True,
    total: int = 90,
    hard_blockers: list[str] | None = None,
    discussion_ready: bool = True,
    open_questions: list[str] | None = None,
    missing_decisions: list[str] | None = None,
    goal: str = "Update README in a minimal way.",
    conversation_language: str = "en",
    last_explicit_language: str = "en",
    task_archetype: str = "docs",
) -> tuple[Path, Path]:
    state_dir = path / ".codex-ralph"
    state_dir.mkdir(parents=True, exist_ok=True)
    goal_spec = state_dir / "goal_spec.json"
    plan_score = state_dir / "plan_score.json"
    gate_pass = discussion_ready and total >= 85 and not hard_blockers
    docs_question = {
        "id": "Q1",
        "decision_key": "audience",
        "prompt": "Who is the primary audience for this document?",
        "options": [
            {
                "id": "A",
                "title": "Operators or contributors",
                "proposal": "Write for engineers who will use or maintain the workflow.",
                "if_chosen": "Content will be practical and implementation-focused.",
                "tradeoff": "Less introductory guidance for newcomers.",
            },
            {
                "id": "B",
                "title": "New adopters",
                "proposal": "Write for users approaching the system for the first time.",
                "if_chosen": "Content will emphasize onboarding clarity.",
                "tradeoff": "Less detail for internal maintainers.",
            },
        ],
        "reply_format": "Choose: A | B\nOptional note: ..."
    }
    feature_ui_question = {
        "id": "Q1",
        "decision_key": "primary_interaction_model",
        "prompt": "What should the primary interaction model be?",
        "options": [
            {
                "id": "A",
                "title": "Keyboard-first",
                "proposal": "Use WASD or arrow keys as the main control scheme.",
                "if_chosen": "Gameplay will be optimized for desktop responsiveness and direct steering.",
                "tradeoff": "Precise and fast, but less natural for casual touch-first play.",
                "value": "keyboard",
            },
            {
                "id": "B",
                "title": "Pointer-first",
                "proposal": "Use mouse or touch direction as the main control scheme.",
                "if_chosen": "Gameplay will optimize for drag or pointer-follow movement.",
                "tradeoff": "More accessible on touch devices, but can feel less precise for arena control.",
                "value": "pointer",
            },
        ],
        "reply_format": "Choose: A | B\nOptional note: ..."
    }
    ready_resolved = {
        "docs": {
            "audience": "contributors",
            "artifact_type": "spec",
            "tone_format": "canonical",
            "acceptance_boundary": "docs_plus_runtime"
        },
        "feature_ui": {
            "primary_interaction_model": "keyboard",
            "target_platform": "desktop_only",
            "core_user_flow": "round_based",
            "success_condition": "timed_score",
            "visual_constraints": "minimal_functional",
        },
    }
    ready_history = {
        "docs": [
            {
                "id": "Q0",
                "prompt": "Who is the primary audience for this document?",
                "selected_option": "A",
                "user_note": "",
                "resolved_decision_key": "audience",
                "language": last_explicit_language,
            }
        ],
        "feature_ui": [
            {
                "id": "Q1",
                "prompt": "What should the primary interaction model be?",
                "selected_option": "A",
                "user_note": "",
                "resolved_decision_key": "primary_interaction_model",
                "language": last_explicit_language,
            },
            {
                "id": "Q2",
                "prompt": "What platform target should this first implementation support?",
                "selected_option": "A",
                "user_note": "",
                "resolved_decision_key": "target_platform",
                "language": last_explicit_language,
            },
            {
                "id": "Q3",
                "prompt": "What match structure should the core user flow use?",
                "selected_option": "A",
                "user_note": "",
                "resolved_decision_key": "core_user_flow",
                "language": last_explicit_language,
            },
            {
                "id": "Q4",
                "prompt": "What should determine victory in the match?",
                "selected_option": "A",
                "user_note": "",
                "resolved_decision_key": "success_condition",
                "language": last_explicit_language,
            },
            {
                "id": "Q5",
                "prompt": "What visual constraint should guide the first version?",
                "selected_option": "B",
                "user_note": "",
                "resolved_decision_key": "visual_constraints",
                "language": last_explicit_language,
            },
        ],
    }
    pending_question = feature_ui_question if task_archetype == "feature_ui" else docs_question
    payload = {
        "project_name": "demo-project",
        "branch_name": "feature/demo",
        "goal": goal,
        "allowed_scope": ["README.md", "src/demo.py", "docs/spec.md"],
        "forbidden_scope": ["payments/", "db/", "infra/"],
        "codebase_evidence": [
            {"claim": "README already exists", "file": "README.md", "lines": "1-5"},
            {"claim": "Documentation entrypoint already exists", "file": "docs/spec.md", "lines": "1-8"},
            {"claim": "Source module exists", "file": "src/demo.py", "lines": "1-20"}
        ],
        "acceptance_criteria": ["README is updated", "verification passes", "scope boundary stays intact"],
        "verification": ["python3 -c \"print('ok')\"", "python3 -c \"print('docs')\""],
        "risks": [
            {"risk": "touch unrelated files", "mitigation": "limit scope to README"},
            {"risk": "weaken documentation contract", "mitigation": "preserve acceptance boundary"},
            {"risk": "miss verification evidence", "mitigation": "run deterministic checks"}
        ],
        "discussion_ready": discussion_ready,
        "discussion_summary": "Scope and verification are clear." if discussion_ready else "The request is still too ambiguous to execute.",
        "conversation_language": conversation_language,
        "last_explicit_language": last_explicit_language,
        "open_questions": open_questions or [],
        "missing_decisions": missing_decisions or [],
        "discussion": {
            "mode": "deep_interview",
            "round": 1,
            "status": "ready" if discussion_ready else "needs_discussion",
            "task_archetype": task_archetype,
            "last_explicit_language": last_explicit_language,
            "current_question": None if discussion_ready else pending_question,
            "history": [] if not discussion_ready else ready_history[task_archetype],
            "resolved_decisions": ready_resolved[task_archetype] if discussion_ready else {},
            "pressure_pass_completed": discussion_ready
        },
        "user_confirmation": confirmed,
        "plan_score": {
            "total": total,
            "decision": "approved" if gate_pass else "blocked",
            "threshold": 85,
            "discussion_ready": discussion_ready,
            "hard_blockers": hard_blockers or [],
            "dimensions": {
                "intent_clarity": 90 if gate_pass else 55
            },
            "gates": {
                "epistemic": {"score": 90 if gate_pass else 55, "threshold": 70, "passed": gate_pass, "blockers": [] if gate_pass else ["required decisions remain unresolved" if not discussion_ready else "epistemic score is below threshold"], "dimensions": {"intent_clarity": 90 if gate_pass else 55}},
                "deontic": {"score": 90 if gate_pass else 60, "threshold": 70, "passed": gate_pass, "blockers": [] if gate_pass else ["decision boundaries are incomplete" if not discussion_ready else "deontic score is below threshold"], "dimensions": {"allowed_scope_explicitness": 90}},
                "dialectical": {"score": 90 if gate_pass else 20, "threshold": 60, "passed": gate_pass, "blockers": [] if gate_pass else ["pressure pass not completed" if not discussion_ready else "dialectical score is below threshold"], "dimensions": {"pressure_pass_completed": 100 if gate_pass else 0}},
            },
        },
    }
    goal_spec.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    plan_score.write_text(json.dumps(payload["plan_score"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return goal_spec, plan_score


class InstallAndRuntimeTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "spec.md").write_text("spec\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "demo.py").write_text("print('demo')\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        env.update(extra)
        return env

    def _run(self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=str(cwd or ROOT),
            env=env or self._env(),
            capture_output=True,
            text=True,
        )

    def _write_stub_claude(self, *, body: str, exit_code: int = 0) -> None:
        script = textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import sys
            print({body!r})
            sys.exit({exit_code})
            """
        )
        path = self.bin_dir / "claude"
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def _init_git_repo(self) -> None:
        self._run("git", "init", cwd=self.repo)
        self._run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        self._run("git", "config", "user.name", "Test User", cwd=self.repo)
        self._run("git", "add", "README.md", "docs/spec.md", "src/demo.py", cwd=self.repo)
        self._run("git", "commit", "-m", "initial", cwd=self.repo)

    def _write_task_graph(self, *, requires_playwright: bool = False) -> Path:
        task_graph = self.repo / ".codex-ralph" / "task_graph_input.json"
        task_graph.parent.mkdir(parents=True, exist_ok=True)
        task_graph.write_text(
            json.dumps(
                {
                    "run_id": "run-v10",
                    "summary": "Implement demo feature",
                    "tasks": [
                        {
                            "task_id": "T1",
                            "title": "Update docs",
                            "description": "Update README with the new behavior.",
                            "dependencies": [],
                            "allowed_scope": ["README.md"],
                            "forbidden_scope": [".git/"],
                            "acceptance_criteria": ["README contains the new behavior"],
                            "verification": ["python3 -c \"print('ok')\""],
                            "requires_playwright": requires_playwright,
                        },
                        {
                            "task_id": "T2",
                            "title": "Update source",
                            "description": "Update source after docs.",
                            "dependencies": ["T1"],
                            "allowed_scope": ["src/demo.py"],
                            "forbidden_scope": [".git/"],
                            "acceptance_criteria": ["source remains importable"],
                            "verification": ["python3 -m py_compile src/demo.py"],
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return task_graph

    def test_install_global_copies_full_skill_package(self) -> None:
        result = self._run("bash", str(ROOT / "install" / "install.sh"), "global")
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.home / ".codex" / "skills" / "codex-claude-ralph"
        self.assertTrue((installed / "SKILL.md").exists())
        self.assertTrue((installed / "runtime" / "orchestrator.py").exists())
        self.assertTrue((installed / "runtime" / "ralph.sh").exists())
        self.assertTrue((installed / "install" / "doctor.sh").exists())
        self.assertTrue((self.home / ".codex" / "hooks" / "codex-claude-ralph.settings.json").exists())

    def test_install_project_copies_full_skill_package(self) -> None:
        result = self._run("bash", str(ROOT / "install" / "install.sh"), "project", "--repo", str(self.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.repo / ".codex" / "skills" / "codex-claude-ralph"
        self.assertTrue((installed / "SKILL.md").exists())
        self.assertTrue((installed / "runtime" / "scripts" / "ralph-skill-run.sh").exists())
        self.assertTrue((installed / "hooks" / "settings.project.json").exists())
        self.assertTrue((self.repo / ".codex" / "hooks" / "codex-claude-ralph.settings.json").exists())

    def test_doctor_reports_missing_claude(self) -> None:
        result = self._run("bash", str(ROOT / "install" / "doctor.sh"), "--repo", str(self.repo), "--json")
        payload = json.loads(result.stdout)
        self.assertIn("runtime_orchestrator", payload)
        self.assertIn("claude_available", payload)
        self.assertIn("codex_available", payload)

    def test_gate_blocks_low_score(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, total=70)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        status = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["stage"], "plan_gate")

    def test_gate_blocks_missing_confirmation(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=False)
        result = self._run(
            "python3",
            str(ROOT / "runtime" / "scripts" / "ralph-gate.py"),
            "--repo",
            str(self.repo),
            "--json",
        )
        self.assertNotEqual(result.returncode, 0)

        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stage"], "approval_pending")

    def test_gate_blocks_when_discussion_is_not_ready(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            total=92,
            discussion_ready=False,
            open_questions=["What are the exact controls?"],
            missing_decisions=["Win condition is undefined"],
        )
        result = self._run(
            "python3",
            str(ROOT / "runtime" / "scripts" / "ralph-gate.py"),
            "--repo",
            str(self.repo),
            "--json",
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIn("GoalSpec discussion_ready is false", payload["reasons"])
        self.assertTrue(any("Open questions remain" in item for item in payload["reasons"]))
        self.assertTrue(any("Missing decisions remain" in item for item in payload["reasons"]))

        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        status = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(status["stage"], "discussion")
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["discussion"]["ready"], False)
        self.assertEqual(status["next_action"], "answer_current_question")

    def test_overall_score_cannot_exceed_84_while_discussion_is_not_ready(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            total=99,
            discussion_ready=False,
            open_questions=["What are the exact controls?"],
            missing_decisions=["Win condition is undefined"],
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertLessEqual(payload["scorecard"]["total"], 84)

    def test_scorecard_contains_all_three_gates(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=False)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertIn("epistemic", payload["scorecard"]["gates"])
        self.assertIn("deontic", payload["scorecard"]["gates"])
        self.assertIn("dialectical", payload["scorecard"]["gates"])

    def test_status_text_renders_single_discussion_question_template(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            discussion_ready=False,
            open_questions=["Who is the primary audience?"],
            missing_decisions=["Audience"],
            conversation_language="en",
            last_explicit_language="en",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "status",
            "--repo",
            str(self.repo),
        )
        self.assertIn("Discussion Round", result.stdout)
        self.assertEqual(result.stdout.count("\nQuestion\n"), 1)
        self.assertIn("Option A", result.stdout)
        self.assertIn("Option B", result.stdout)

    def test_status_json_exposes_scorecard_and_next_action(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=False)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertIn("scorecard", payload)
        self.assertIn("next_action", payload)
        self.assertIn("ui_prompt", payload)
        self.assertIn("task_graph", payload)
        self.assertIn("active_workers", payload)
        self.assertIn("review_queue", payload)

    def test_status_json_exposes_ui_prompt_for_discussion(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            discussion_ready=False,
            open_questions=["Who is the primary audience?"],
            missing_decisions=["Audience"],
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(payload["ui_prompt"]["type"], "single_choice")
        self.assertEqual(len(payload["ui_prompt"]["options"]), 2)
        self.assertEqual(payload["ui_prompt"]["language"], "en")

    def test_answer_command_advances_discussion_and_updates_state(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            goal="Build a browser game UI",
            discussion_ready=False,
            open_questions=["What should the primary interaction model be?"],
            missing_decisions=["Primary interaction model"],
            task_archetype="feature_ui",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        answer = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "answer",
            "--repo",
            str(self.repo),
            "--choice",
            "A",
            "--note",
            "Desktop keyboard is better",
            "--language",
            "en",
            "--json",
        )
        self.assertEqual(answer.returncode, 0, answer.stderr)
        payload = json.loads(answer.stdout)
        self.assertEqual(payload["discussion"]["history"][0]["selected_option"], "A")
        self.assertEqual(payload["discussion"]["history"][0]["resolved_decision_key"], "primary_interaction_model")
        self.assertEqual(payload["discussion"]["current_question"]["decision_key"], "target_platform")
        self.assertEqual(payload["next_action"], "answer_current_question")

    def test_answer_command_preserves_language_for_short_choice_rounds(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            goal="黑洞吞建筑成长网页小游戏",
            discussion_ready=False,
            open_questions=["What should the primary interaction model be?"],
            missing_decisions=["Primary interaction model"],
            conversation_language="zh",
            last_explicit_language="zh",
            task_archetype="feature_ui",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        answer = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "answer",
            "--repo",
            str(self.repo),
            "--choice",
            "A",
            "--json",
        )
        self.assertEqual(answer.returncode, 0, answer.stderr)
        payload = json.loads(answer.stdout)
        self.assertEqual(payload["conversation_language"], "zh")
        self.assertEqual(payload["last_explicit_language"], "zh")

    def test_status_text_renders_chinese_when_language_is_zh(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            goal="黑洞吞建筑成长网页小游戏",
            discussion_ready=False,
            open_questions=["What should the primary interaction model be?"],
            missing_decisions=["Primary interaction model"],
            conversation_language="zh",
            last_explicit_language="zh",
            task_archetype="feature_ui",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "status",
            "--repo",
            str(self.repo),
        )
        self.assertIn("讨论轮次", result.stdout)
        self.assertIn("回复格式", result.stdout)
        self.assertIn("当前需求仍然过于模糊", result.stdout)
        self.assertIn("黑洞吞建筑成长网页小游戏", result.stdout)

    def test_status_text_renders_english_when_language_is_en(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            goal="Build a browser game UI",
            discussion_ready=False,
            open_questions=["What should the primary interaction model be?"],
            missing_decisions=["Primary interaction model"],
            conversation_language="en",
            last_explicit_language="en",
            task_archetype="feature_ui",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "status",
            "--repo",
            str(self.repo),
        )
        self.assertIn("Discussion Round", result.stdout)
        self.assertIn("Reply Format", result.stdout)

    def test_final_confirmation_only_valid_in_approval_pending(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=False)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(payload["stage"], "approval_pending")
        self.assertEqual(payload["next_action"], "confirm_run")

    def test_scorecard_recomputes_and_drops_stale_blockers_after_discussion_ready(self) -> None:
        goal_spec, _ = write_goal_spec(
            self.repo,
            total=67,
            hard_blockers=["pressure pass not completed", "Primary interaction model"],
            discussion_ready=True,
            confirmed=False,
            goal="黑洞吞建筑成长网页小游戏",
            conversation_language="zh",
            last_explicit_language="zh",
            task_archetype="feature_ui",
        )
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        payload = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(payload["discussion"]["ready"], True)
        self.assertEqual(payload["scorecard"]["hard_blockers"], [])
        self.assertGreaterEqual(payload["scorecard"]["total"], 85)
        self.assertEqual(payload["stage"], "approval_pending")

    def test_runtime_run_writes_status_events_and_artifacts(self) -> None:
        self._write_stub_claude(body=json.dumps({
            "structured_output": {
                "status": "success",
                "summary": "worker finished",
                "changed_files": ["README.md"],
                "tests_run": ["python3 -c \"print('ok')\""],
                "blockers": [],
            }
        }))
        goal_spec, _ = write_goal_spec(self.repo)

        result = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        status = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(status["stage"], "complete")
        self.assertEqual(status["status"], "passed")
        self.assertEqual(status["progress"]["completed"], 1)
        self.assertEqual(status["progress"]["total"], 1)
        runs = list((self.repo / ".codex-ralph" / "runs").glob("*_S1_worker.json"))
        self.assertEqual(len(runs), 1)
        events = (self.repo / ".codex-ralph" / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"stage": "worker"', events)
        self.assertIn('"stage": "tests"', events)
        self.assertIn('"stage": "review"', events)

    def test_runtime_run_surfaces_visual_monitor(self) -> None:
        self._write_stub_claude(body=json.dumps({
            "structured_output": {
                "status": "success",
                "summary": "worker finished",
                "changed_files": ["README.md"],
                "tests_run": [],
                "blockers": [],
            }
        }))
        goal_spec, _ = write_goal_spec(self.repo)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
            "--visual",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ralph Run Monitor", result.stdout)
        self.assertIn("Story: S1", result.stdout)

    def test_runtime_run_blocks_on_worker_blocked(self) -> None:
        self._write_stub_claude(body=json.dumps({
            "structured_output": {
                "status": "blocked",
                "summary": "need more context",
                "changed_files": [],
                "tests_run": [],
                "blockers": ["missing requirement"],
            }
        }))
        goal_spec, _ = write_goal_spec(self.repo)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["stage"], "failed")

    def test_runtime_run_treats_manual_verification_lines_as_non_blocking(self) -> None:
        self._write_stub_claude(body=json.dumps({
            "structured_output": {
                "status": "success",
                "summary": "worker finished",
                "changed_files": ["index.html", "game.js"],
                "tests_run": [],
                "blockers": [],
            }
        }))
        goal_spec, _ = write_goal_spec(
            self.repo,
            goal="Build a browser-only game.",
            task_archetype="feature_ui",
        )
        payload = json.loads(goal_spec.read_text(encoding="utf-8"))
        payload["verification"] = [
            "Open index.html locally and play a round.",
            "Confirm movement, consumption, AI competition, score updates, and replay behavior.",
        ]
        goal_spec.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        result = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        status = json.loads(
            self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "status",
                "--repo",
                str(self.repo),
                "--json",
            ).stdout
        )
        self.assertEqual(status["stage"], "complete")
        self.assertEqual(status["status"], "passed")

        tests_outputs = list((self.repo / ".codex-ralph" / "runs").glob("*_S1_tests.json"))
        self.assertEqual(len(tests_outputs), 1)
        test_results = json.loads(tests_outputs[0].read_text(encoding="utf-8"))
        self.assertEqual([item["status"] for item in test_results], ["manual", "manual"])

    def test_v10_plan_persists_task_graph_and_blocks_for_approval(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        task_graph = self._write_task_graph(requires_playwright=True)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "plan",
            "--repo",
            str(self.repo),
            "--task-graph",
            str(task_graph),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stage"], "task_graph_pending")
        self.assertEqual(payload["next_action"], "approve_task_graph")
        self.assertEqual(payload["task_graph"]["batches"][0]["tasks"], ["T1"])
        self.assertTrue(payload["task_graph"]["tasks"][0]["requires_playwright"])

    def test_v10_launch_creates_git_worktree_and_visible_terminal_command(self) -> None:
        self._init_git_repo()
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        task_graph = self._write_task_graph()
        plan = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "plan",
            "--repo",
            str(self.repo),
            "--task-graph",
            str(task_graph),
            "--json",
        )
        self.assertEqual(plan.returncode, 0, plan.stderr)
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "launch",
            "--repo",
            str(self.repo),
            "--task-id",
            "T1",
            "--run-id",
            "run-v10",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["worktree"]).exists())
        self.assertEqual(payload["branch"], "codex-ralph/run-v10/T1")
        self.assertEqual(payload["terminal_command"][0], "osascript")
        graph = json.loads((self.repo / ".codex-ralph" / "task_graph.json").read_text(encoding="utf-8"))
        self.assertEqual(graph["tasks"][0]["status"], "worker_running")

    def test_v10_review_rework_limit_enters_handoff_decision(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        task_graph = self._write_task_graph()
        plan = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "plan",
            "--repo",
            str(self.repo),
            "--task-graph",
            str(task_graph),
            "--json",
        )
        self.assertEqual(plan.returncode, 0, plan.stderr)
        review = self.repo / ".codex-ralph" / "review.json"
        review.write_text(
            json.dumps(
                {
                    "scores": {
                        "requirements_fit": 20,
                        "acceptance_coverage": 20,
                        "scope_compliance": 80,
                        "verification_evidence": 0,
                        "integration_risk": 50,
                        "ux_or_runtime_quality": 10,
                    },
                    "blocking_issues": ["missing core behavior"],
                    "rework_instructions": ["implement the missing behavior"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        payload = None
        for _ in range(3):
            result = self._run(
                "bash",
                str(ROOT / "runtime" / "ralph.sh"),
                "review-mark",
                "--repo",
                str(self.repo),
                "--task-id",
                "T1",
                "--verdict",
                "rework",
                "--review",
                str(review),
                "--run-id",
                "run-v10",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["stage"], "handoff_decision")
        self.assertEqual(payload["next_action"], "choose_handoff")
        self.assertEqual(payload["handoff_options"], ["continue_claude_rework", "codex_takeover"])

    def test_v10_collect_commits_worktree_changes_for_merge(self) -> None:
        self._init_git_repo()
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        init = self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        task_graph = self._write_task_graph()
        self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "plan",
            "--repo",
            str(self.repo),
            "--task-graph",
            str(task_graph),
            "--json",
        )
        launch = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "launch",
            "--repo",
            str(self.repo),
            "--task-id",
            "T1",
            "--run-id",
            "run-v10",
        )
        self.assertEqual(launch.returncode, 0, launch.stderr)
        launch_payload = json.loads(launch.stdout)
        worktree = Path(launch_payload["worktree"])
        (worktree / "README.md").write_text("base\nupdated\n", encoding="utf-8")
        output = self.repo / ".codex-ralph" / "runs" / "run-v10" / "tasks" / "T1" / "worker_output.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"status": "success", "summary": "updated", "changed_files": ["README.md"], "tests_run": [], "blockers": [], "notes_for_reviewer": []})
            + "\n",
            encoding="utf-8",
        )
        collect = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "collect",
            "--repo",
            str(self.repo),
            "--task-id",
            "T1",
            "--run-id",
            "run-v10",
        )
        self.assertEqual(collect.returncode, 0, collect.stderr)
        payload = json.loads(collect.stdout)
        self.assertTrue(payload["commit"]["committed"])
        graph = json.loads((self.repo / ".codex-ralph" / "task_graph.json").read_text(encoding="utf-8"))
        self.assertTrue(graph["tasks"][0]["commit"])

    def test_v10_handoff_records_codex_takeover(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        state_path = self.repo / ".codex-ralph" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["stage"] = "handoff_decision"
        state["status"] = "blocked"
        state["handoff_options"] = ["continue_claude_rework", "codex_takeover"]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "handoff",
            "--repo",
            str(self.repo),
            "--mode",
            "codex_takeover",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["next_action"], "codex_takeover")
        self.assertEqual(payload["message"], "User selected Codex/GPT takeover in the current conversation.")

    def test_v10_playwright_generates_smoke_spec(self) -> None:
        goal_spec, _ = write_goal_spec(self.repo, confirmed=True)
        self._run(
            "bash",
            str(ROOT / "runtime" / "scripts" / "ralph-skill-run.sh"),
            "--repo",
            str(self.repo),
            "--goal-spec",
            str(goal_spec),
            "--allow-non-git",
        )
        task_graph = self._write_task_graph(requires_playwright=True)
        self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "plan",
            "--repo",
            str(self.repo),
            "--task-graph",
            str(task_graph),
            "--json",
        )
        result = self._run(
            "bash",
            str(ROOT / "runtime" / "ralph.sh"),
            "playwright",
            "--repo",
            str(self.repo),
            "--task-id",
            "T1",
            "--url",
            "http://127.0.0.1:4173",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        spec_path = Path(payload["spec_path"])
        self.assertTrue(spec_path.exists())
        spec = spec_path.read_text(encoding="utf-8")
        self.assertIn("@playwright/test", spec)
        self.assertIn("canvas", spec)
        self.assertIn("http://127.0.0.1:4173", spec)


if __name__ == "__main__":
    unittest.main()
