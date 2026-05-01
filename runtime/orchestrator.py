#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 600
PLAN_THRESHOLD = 85
GATE_THRESHOLDS = {"epistemic": 70, "deontic": 70, "dialectical": 60}
MAX_REWORK_ATTEMPTS = 3
STORY_STATUSES = {"pending", "running", "passed", "blocked", "failed"}
DISCUSSION_NEXT_ACTIONS = {
    "answer_current_question",
    "continue_discussion",
    "review_scorecard",
    "confirm_run",
    "wait_for_worker",
    "inspect_failure",
    "approve_task_graph",
    "launch_worker",
    "collect_worker",
    "review_worker",
    "launch_rework",
    "merge_task",
    "final_review",
    "choose_handoff",
    "codex_takeover",
}
REVIEW_SCORE_KEYS = [
    "requirements_fit",
    "acceptance_coverage",
    "scope_compliance",
    "verification_evidence",
    "integration_risk",
    "ux_or_runtime_quality",
]

SKILL_ROOT = Path(os.environ.get("SKILL_ROOT") or Path(__file__).resolve().parents[1]).resolve()
RUNTIME_ROOT = SKILL_ROOT / "runtime"
RUNTIME_SCRIPTS_DIR = RUNTIME_ROOT / "scripts"
SCHEMAS_DIR = RUNTIME_ROOT / "schemas"

TASK_DECISION_CHECKLISTS: dict[str, list[str]] = {
    "feature_ui": [
        "primary_interaction_model",
        "target_platform",
        "core_user_flow",
        "success_condition",
        "visual_constraints",
    ],
    "bugfix": [
        "expected_behavior",
        "failing_scenario",
        "non_regression_boundary",
        "verification_path",
    ],
    "refactor": [
        "preserved_invariants",
        "allowed_behavior_changes",
        "scope_boundary",
        "verification_path",
    ],
    "docs": [
        "audience",
        "artifact_type",
        "tone_format",
        "acceptance_boundary",
    ],
    "other": [
        "target_artifact",
        "expected_outcome",
        "scope_boundary",
        "constraints",
        "success_criteria",
    ],
}

DECISION_LABELS = {
    "primary_interaction_model": "Primary interaction model",
    "target_platform": "Target platform",
    "core_user_flow": "Core user flow",
    "success_condition": "Success condition",
    "visual_constraints": "Visual or UX constraints",
    "expected_behavior": "Expected behavior",
    "failing_scenario": "Failing scenario",
    "non_regression_boundary": "Non-regression boundary",
    "verification_path": "Verification path",
    "preserved_invariants": "Preserved invariants",
    "allowed_behavior_changes": "Allowed behavior changes",
    "scope_boundary": "Scope boundary",
    "audience": "Audience",
    "artifact_type": "Artifact type",
    "tone_format": "Tone or format",
    "acceptance_boundary": "Acceptance boundary",
    "target_artifact": "Target artifact",
    "expected_outcome": "Expected outcome",
    "constraints": "Constraints",
    "success_criteria": "Success criteria",
    "pressure_pass": "Dialectical pressure pass",
}

LANGUAGES = {"zh", "en"}

SYSTEM_COPY = {
    "zh": {
        "discussion_round": "讨论轮次",
        "current_understanding": "当前理解",
        "goal": "目标",
        "current_best_interpretation": "当前最佳理解",
        "why_blocked": "当前仍被阻断的原因",
        "question": "问题",
        "option": "选项",
        "proposal": "方案",
        "if_chosen": "如果选择",
        "tradeoff": "权衡",
        "reply_format": "回复格式",
        "choose": "选择",
        "optional_note": "可选备注",
        "discussion_blocked": "在执行前仍需继续讨论，关键决策尚未收敛。",
        "discussion_ready": "讨论已完成，工作流可进入最终确认。",
        "status_discussion_blocked": "讨论尚未完成，当前不能执行。",
        "status_plan_gate_blocked": "计划就绪评分卡未通过。",
        "status_approval_required": "运行前仍需最终确认。",
        "status_initialized": "Ralph 运行时已初始化。",
        "native_prompt_title": "Discussion Round {round}",
        "native_prompt_title_zh": "讨论轮次 {round}",
        "native_reply_hint": "Reply with one option only: {choices}",
        "native_reply_hint_zh": "请只回复一个选项：{choices}",
        "scorecard_title": "计划就绪评分卡",
        "overall": "总体",
        "score": "分数",
        "decision": "决策",
        "threshold": "阈值",
        "gate_epistemic": "认知门",
        "gate_deontic": "边界门",
        "gate_dialectical": "辩证门",
        "status": "状态",
        "dimensions": "维度",
        "hard_blockers": "硬阻断项",
        "open_questions": "待解问题",
        "missing_decisions": "缺失决策",
        "next_action": "下一步",
        "execution_approval": "执行确认",
        "ready_to_run": "准备执行",
        "scope": "范围",
        "verification": "验证",
        "risks": "风险",
        "confirmation_required": "需要确认",
        "confirm_run": "请准确回复：confirm run",
        "stage_update": "阶段更新",
        "stage": "阶段",
        "current_story": "当前故事",
        "next": "下一步",
        "stage_failed": "阶段失败",
        "reason": "原因",
        "evidence": "证据",
        "suggested_next_step": "建议下一步",
        "none": "无",
        "pass": "通过",
        "blocked": "阻断",
        "running": "运行中",
        "failed": "失败",
        "passed": "通过",
    },
    "en": {},
}

SYSTEM_COPY["en"] = {
    "discussion_round": "Discussion Round",
    "current_understanding": "Current Understanding",
    "goal": "Goal",
    "current_best_interpretation": "Current best interpretation",
    "why_blocked": "Why this is still blocked",
    "question": "Question",
    "option": "Option",
    "proposal": "Proposal",
    "if_chosen": "If chosen",
    "tradeoff": "Tradeoff",
    "reply_format": "Reply Format",
    "choose": "Choose",
    "optional_note": "Optional note",
    "discussion_blocked": "Discussion is still required before execution. Key decisions remain unresolved.",
    "discussion_ready": "Discussion is complete and the workflow is ready for final approval.",
    "status_discussion_blocked": "Discussion is still required before execution.",
    "status_plan_gate_blocked": "Plan readiness scorecard is blocked.",
    "status_approval_required": "Final confirmation is required before execution.",
    "status_initialized": "Initialized Ralph runtime state.",
    "native_prompt_title": "Discussion Round {round}",
    "native_reply_hint": "Reply with one option only: {choices}",
    "scorecard_title": "Plan Readiness Scorecard",
    "overall": "Overall",
    "score": "Score",
    "decision": "Decision",
    "threshold": "Threshold",
    "gate_epistemic": "Epistemic Gate",
    "gate_deontic": "Deontic Gate",
    "gate_dialectical": "Dialectical Gate",
    "status": "Status",
    "dimensions": "Dimensions",
    "hard_blockers": "Hard Blockers",
    "open_questions": "Open Questions",
    "missing_decisions": "Missing Decisions",
    "next_action": "Next Action",
    "execution_approval": "Execution Approval",
    "ready_to_run": "Ready to Run",
    "scope": "Scope",
    "verification": "Verification",
    "risks": "Risks",
    "confirmation_required": "Confirmation Required",
    "confirm_run": "Reply exactly: confirm run",
    "stage_update": "Stage Update",
    "stage": "Stage",
    "current_story": "Current Story",
    "next": "Next",
    "stage_failed": "Stage Failed",
    "reason": "Reason",
    "evidence": "Evidence",
    "suggested_next_step": "Suggested Next Step",
    "none": "none",
    "pass": "pass",
    "blocked": "blocked",
    "running": "running",
    "failed": "failed",
    "passed": "passed",
}

DECISION_LABELS_ZH = {
    "primary_interaction_model": "主要交互方式",
    "target_platform": "目标平台",
    "core_user_flow": "核心用户流程",
    "success_condition": "胜利条件",
    "visual_constraints": "视觉或体验约束",
    "expected_behavior": "预期行为",
    "failing_scenario": "失败场景",
    "non_regression_boundary": "非回归边界",
    "verification_path": "验证路径",
    "preserved_invariants": "需保持的不变量",
    "allowed_behavior_changes": "允许的行为变化",
    "scope_boundary": "范围边界",
    "audience": "目标读者",
    "artifact_type": "产物类型",
    "tone_format": "语气或格式",
    "acceptance_boundary": "验收边界",
    "target_artifact": "目标产物",
    "expected_outcome": "期望结果",
    "constraints": "约束条件",
    "success_criteria": "成功标准",
    "pressure_pass": "辩证压力测试",
}

QUESTION_COPY_ZH = {
    "primary_interaction_model": {
        "prompt": "这一版主要交互方式应该是什么？",
        "options": {
            "A": {
                "title": "键盘优先",
                "proposal": "使用 WASD 或方向键作为主要控制方式。",
                "if_chosen": "玩法会针对桌面端即时操控和精确转向优化。",
                "tradeoff": "更精准更快，但对休闲触屏用户不够自然。",
            },
            "B": {
                "title": "指针优先",
                "proposal": "使用鼠标或触控方向作为主要控制方式。",
                "if_chosen": "玩法会围绕拖拽或指针跟随移动来设计。",
                "tradeoff": "更适合触屏设备，但在竞技控制上可能不如键盘精准。",
            },
        },
    },
    "target_platform": {
        "prompt": "这一版首先应该支持什么平台？",
        "options": {
            "A": {
                "title": "桌面端优先",
                "proposal": "v1 只针对桌面浏览器优化。",
                "if_chosen": "输入、布局和数值平衡可以更简单，开发更快。",
                "tradeoff": "移动端支持会延后。",
            },
            "B": {
                "title": "桌面加移动",
                "proposal": "v1 同时支持桌面浏览器和触屏移动浏览器。",
                "if_chosen": "游戏循环和 HUD 从一开始就需要响应式和触控适配。",
                "tradeoff": "实现范围和调优复杂度都会更高。",
            },
        },
    },
    "core_user_flow": {
        "prompt": "核心对局流程应该采用什么结构？",
        "options": {
            "A": {
                "title": "回合制对局",
                "proposal": "开始一局，争夺建筑，达到结束状态后允许重开。",
                "if_chosen": "游戏会有明确的开始、结束和再来一局循环。",
                "tradeoff": "需要更明确的状态机设计。",
            },
            "B": {
                "title": "无限竞技场",
                "proposal": "直接进入无尽生存或刷分模式。",
                "if_chosen": "实现可以更聚焦连续游玩，不需要硬性终局。",
                "tradeoff": "对“人机竞赛”这个目标的收束感更弱。",
            },
        },
    },
    "success_condition": {
        "prompt": "胜负应该由什么来决定？",
        "options": {
            "A": {
                "title": "限时比分赛",
                "proposal": "在限定时间内比最终得分或体积大小。",
                "if_chosen": "HUD 和重开流程会突出倒计时与分差。",
                "tradeoff": "玩家可能在没有直接碰撞对抗的情况下输掉比赛。",
            },
            "B": {
                "title": "目标体积或淘汰",
                "proposal": "先达到目标体积，或直接吞掉对手即获胜。",
                "if_chosen": "成长节奏和正面对抗会成为玩法核心。",
                "tradeoff": "碰撞和成长规则需要更仔细平衡。",
            },
        },
    },
    "visual_constraints": {
        "prompt": "第一版应该遵循什么视觉约束？",
        "options": {
            "A": {
                "title": "精致街机感",
                "proposal": "做成更有风格的街机表现，加入明显的 HUD 动效反馈。",
                "if_chosen": "CSS 和 canvas 渲染会偏向更强的动效和视觉强调。",
                "tradeoff": "实现范围会略大一些。",
            },
            "B": {
                "title": "简洁可玩优先",
                "proposal": "第一版先保持视觉简洁，把重点放在玩法机制。",
                "if_chosen": "实现会更轻量也更稳。",
                "tradeoff": "上线时的高级感会弱一些。",
            },
        },
    },
    "expected_behavior": {
        "prompt": "修复后应以哪种正确行为为准？",
        "options": {
            "A": {
                "title": "以用户观察到的行为为准",
                "proposal": "严格匹配用户描述的期望行为。",
                "if_chosen": "修复会优先满足可见体验正确性。",
                "tradeoff": "内部清理可能后置。",
            },
            "B": {
                "title": "以契约级正确性为准",
                "proposal": "先修复底层契约，再让上层体验回归正确。",
                "if_chosen": "方案会更关注系统不变量和长期安全性。",
                "tradeoff": "可能需要更广的改动。",
            },
        },
    },
    "failing_scenario": {
        "prompt": "哪个失败场景应该定义这次 bugfix 的范围？",
        "options": {
            "A": {
                "title": "单个具体场景",
                "proposal": "把范围收敛到一个可稳定复现的失败路径。",
                "if_chosen": "验证更聚焦，风险更低。",
                "tradeoff": "相邻问题可能暂时保留。",
            },
            "B": {
                "title": "一类相关场景",
                "proposal": "把同一根因引起的一类失败一起修掉。",
                "if_chosen": "补丁会更具预防性。",
                "tradeoff": "更容易带来更大的行为变化。",
            },
        },
    },
    "non_regression_boundary": {
        "prompt": "非回归边界要多严格？",
        "options": {
            "A": {
                "title": "严格收紧",
                "proposal": "除非明确需要，否则保持相邻现有行为不变。",
                "if_chosen": "补丁会更窄更可预测。",
                "tradeoff": "一些顺手清理会被延后。",
            },
            "B": {
                "title": "允许顺带清理",
                "proposal": "在修 bug 的同时允许做相邻清理。",
                "if_chosen": "可以顺手修掉相关技术债。",
                "tradeoff": "回归风险更高。",
            },
        },
    },
    "verification_path": {
        "prompt": "验证路径应以什么为主？",
        "options": {
            "A": {
                "title": "自动化验证优先",
                "proposal": "尽量依赖确定性的测试或命令验证。",
                "if_chosen": "验收证据会更稳定，便于复查。",
                "tradeoff": "前置搭建成本更高。",
            },
            "B": {
                "title": "人工复现优先",
                "proposal": "以人工复现和手动检查作为主要验证方式。",
                "if_chosen": "短期推进更快。",
                "tradeoff": "可重复性和回归保护会更弱。",
            },
        },
    },
    "preserved_invariants": {
        "prompt": "这次重构最应锁定的是什么？",
        "options": {
            "A": {
                "title": "行为保持不变",
                "proposal": "优先保证外部行为完全不变。",
                "if_chosen": "重构重点会放在内部结构改善。",
                "tradeoff": "结构上的激进优化会受限。",
            },
            "B": {
                "title": "接口保持不变",
                "proposal": "优先保证对外接口不变，允许内部行为小幅调整。",
                "if_chosen": "内部重构空间更大。",
                "tradeoff": "需要更细致地说明允许变化的边界。",
            },
        },
    },
    "allowed_behavior_changes": {
        "prompt": "是否允许这次重构带来行为变化？",
        "options": {
            "A": {
                "title": "尽量不变",
                "proposal": "默认不接受任何可见行为变化。",
                "if_chosen": "实现会更保守。",
                "tradeoff": "一些结构问题可能暂时保留。",
            },
            "B": {
                "title": "允许小幅改善",
                "proposal": "允许与重构目标一致的小幅行为改良。",
                "if_chosen": "可以顺带改善局部体验或一致性。",
                "tradeoff": "需要更严格验收边界。",
            },
        },
    },
    "scope_boundary": {
        "prompt": "这次工作的范围边界应该怎么定？",
        "options": {
            "A": {
                "title": "严格单模块",
                "proposal": "范围尽量限制在单一模块或单一职责内。",
                "if_chosen": "改动面更可控。",
                "tradeoff": "跨模块根因可能留到后续。",
            },
            "B": {
                "title": "允许跨模块闭环",
                "proposal": "只要是为完成目标所必需，允许跨模块收口。",
                "if_chosen": "更容易一次性解决系统性问题。",
                "tradeoff": "实现和评审成本更高。",
            },
        },
    },
    "audience": {
        "prompt": "这份文档的主要读者是谁？",
        "options": {
            "A": {
                "title": "维护者或贡献者",
                "proposal": "面向会使用或维护这个 workflow 的工程师来写。",
                "if_chosen": "内容会更务实、更偏实现。",
                "tradeoff": "对新用户的引导会更少。",
            },
            "B": {
                "title": "首次接触的新用户",
                "proposal": "面向第一次接触系统的用户来写。",
                "if_chosen": "内容会更强调上手清晰度。",
                "tradeoff": "对内部维护细节会更少。",
            },
        },
    },
    "artifact_type": {
        "prompt": "这次文档最适合产出成什么类型？",
        "options": {
            "A": {
                "title": "规范或设计文档",
                "proposal": "产出偏规范、契约、设计说明的文档。",
                "if_chosen": "内容会更适合作为长期参考。",
                "tradeoff": "阅读门槛略高。",
            },
            "B": {
                "title": "上手指南",
                "proposal": "产出偏操作步骤和示例的指南。",
                "if_chosen": "更利于快速使用。",
                "tradeoff": "长期契约表达可能不够完整。",
            },
        },
    },
    "tone_format": {
        "prompt": "文档语气和格式应该以哪种风格为主？",
        "options": {
            "A": {
                "title": "规范式",
                "proposal": "采用偏正式、结构化、可引用的写法。",
                "if_chosen": "更适合成为长期规则文档。",
                "tradeoff": "可读性会稍显硬。",
            },
            "B": {
                "title": "教程式",
                "proposal": "采用更易读、按步骤展开的写法。",
                "if_chosen": "更适合快速传播和上手。",
                "tradeoff": "规则边界表达可能更弱。",
            },
        },
    },
    "acceptance_boundary": {
        "prompt": "文档完成的验收边界应该落在哪里？",
        "options": {
            "A": {
                "title": "只更新文档",
                "proposal": "只要求文档本身完整正确。",
                "if_chosen": "范围最小，推进最快。",
                "tradeoff": "可能与 runtime 现实略有偏差。",
            },
            "B": {
                "title": "文档与 runtime 一起对齐",
                "proposal": "要求文档与当前 runtime 行为一致。",
                "if_chosen": "结果更可靠，可直接执行。",
                "tradeoff": "需要额外核对实现。",
            },
        },
    },
    "target_artifact": {
        "prompt": "这次任务最终最关键的产物应该是什么？",
        "options": {
            "A": {
                "title": "代码产物",
                "proposal": "以可运行实现为核心交付。",
                "if_chosen": "计划会偏向工程落地。",
                "tradeoff": "说明材料可能更精简。",
            },
            "B": {
                "title": "设计或说明产物",
                "proposal": "以文档、方案、规范为核心交付。",
                "if_chosen": "计划会更强调边界、结构和论证。",
                "tradeoff": "实际实现可能延后。",
            },
        },
    },
    "expected_outcome": {
        "prompt": "这次工作的期望结果应该如何定义？",
        "options": {
            "A": {
                "title": "明确完成态",
                "proposal": "先定义一个明确可验收的完成状态。",
                "if_chosen": "工作流更容易收口。",
                "tradeoff": "探索空间更少。",
            },
            "B": {
                "title": "探索式推进",
                "proposal": "允许结果在推进中逐步收敛。",
                "if_chosen": "更适合开放问题。",
                "tradeoff": "前期 readiness 会更难达标。",
            },
        },
    },
    "constraints": {
        "prompt": "这次任务应优先受到什么约束？",
        "options": {
            "A": {
                "title": "速度优先",
                "proposal": "优先在较短时间内拿到可用结果。",
                "if_chosen": "计划会倾向更小范围、更快落地。",
                "tradeoff": "完整性可能略弱。",
            },
            "B": {
                "title": "质量优先",
                "proposal": "优先在范围内拿到更完整、更正确的结果。",
                "if_chosen": "工作流可以接受更严格的收口动作。",
                "tradeoff": "实现成本更高。",
            },
        },
    },
    "success_criteria": {
        "prompt": "在执行前，成功标准应该明确到什么程度？",
        "options": {
            "A": {
                "title": "严格验收清单",
                "proposal": "执行前必须形成明确清单。",
                "if_chosen": "审批质量会更高。",
                "tradeoff": "前置讨论会更多。",
            },
            "B": {
                "title": "弹性结果框架",
                "proposal": "如果任务偏探索型，允许更宽泛的成功定义。",
                "if_chosen": "工作流会更灵活。",
                "tradeoff": "readiness 更可能长期偏低。",
            },
        },
    },
    "pressure_pass": {
        "prompt": "压力测试轮：执行前最需要锁定哪类挑战？",
        "options": {
            "A": {
                "title": "收紧验收和矛盾处理",
                "proposal": "要求在运行前先明确验收边界并解决矛盾。",
                "if_chosen": "工作流会优先保证执行标准可辩护。",
                "tradeoff": "实现开始前的 rigor 会更高。",
            },
            "B": {
                "title": "缩小范围降低歧义",
                "proposal": "如果验收或边界仍有张力，就主动收窄范围。",
                "if_chosen": "工作流会通过更小范围来降低风险。",
                "tradeoff": "第一版结果可能小于最初设想。",
            },
        },
    },
}

STAGE_LABELS_ZH = {
    "discussion": "讨论中",
    "plan_gate": "计划门禁",
    "approval_pending": "等待确认",
    "init": "初始化",
    "run": "运行中",
    "worker": "执行代理",
    "tests": "测试",
    "review": "复核",
    "complete": "完成",
    "failed": "失败",
}

QUESTION_BANK: dict[str, dict[str, dict[str, Any]]] = {
    "feature_ui": {
        "primary_interaction_model": {
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
        },
        "target_platform": {
            "prompt": "What platform target should this first implementation support?",
            "options": [
                {
                    "id": "A",
                    "title": "Desktop-first",
                    "proposal": "Optimize the game for desktop browsers only in v1.",
                    "if_chosen": "Input, layout, and balancing can stay simpler and faster to implement.",
                    "tradeoff": "Mobile support is postponed.",
                    "value": "desktop_only",
                },
                {
                    "id": "B",
                    "title": "Desktop plus mobile",
                    "proposal": "Support both desktop and touch mobile browsers in v1.",
                    "if_chosen": "The game loop and HUD must be responsive and touch-aware from the start.",
                    "tradeoff": "Higher implementation scope and tuning complexity.",
                    "value": "desktop_and_mobile",
                },
            ],
        },
        "core_user_flow": {
            "prompt": "What match structure should the core user flow use?",
            "options": [
                {
                    "id": "A",
                    "title": "Round-based match",
                    "proposal": "Start match, race for buildings, reach an end state, then allow replay.",
                    "if_chosen": "The game will have a clear start, finish, and restart loop.",
                    "tradeoff": "More explicit game-state logic is required.",
                    "value": "round_based",
                },
                {
                    "id": "B",
                    "title": "Endless arena",
                    "proposal": "Drop directly into an endless survival or score-chasing mode.",
                    "if_chosen": "The implementation can focus on continuous play without a hard finish.",
                    "tradeoff": "Weaker closure for the 人机竞赛 requirement.",
                    "value": "endless",
                },
            ],
        },
        "success_condition": {
            "prompt": "What should determine victory in the match?",
            "options": [
                {
                    "id": "A",
                    "title": "Timed score match",
                    "proposal": "Run a time-limited match and compare final scores or mass.",
                    "if_chosen": "The HUD and replay loop will emphasize countdown and score delta.",
                    "tradeoff": "The player may lose without a direct confrontation.",
                    "value": "timed_score",
                },
                {
                    "id": "B",
                    "title": "Target mass or elimination",
                    "proposal": "Win by reaching a target size first or swallowing the rival.",
                    "if_chosen": "Growth pacing and direct rivalry become the center of the game.",
                    "tradeoff": "Balancing collision and growth rules becomes more important.",
                    "value": "mass_or_elimination",
                },
            ],
        },
        "visual_constraints": {
            "prompt": "What visual constraint should guide the first version?",
            "options": [
                {
                    "id": "A",
                    "title": "Polished arcade",
                    "proposal": "Aim for a polished stylized arcade presentation with animated HUD feedback.",
                    "if_chosen": "CSS and canvas rendering will favor stronger motion and visual emphasis.",
                    "tradeoff": "Slightly more implementation scope.",
                    "value": "polished_arcade",
                },
                {
                    "id": "B",
                    "title": "Minimal functional",
                    "proposal": "Keep the first version visually simple and focus on game mechanics first.",
                    "if_chosen": "Implementation stays leaner and more robust.",
                    "tradeoff": "The page may feel less premium at launch.",
                    "value": "minimal_functional",
                },
            ],
        },
    },
    "bugfix": {
        "expected_behavior": {
            "prompt": "What behavior should be considered correct after the fix?",
            "options": [
                {
                    "id": "A",
                    "title": "Exact user-observed behavior",
                    "proposal": "Match the user’s described desired behavior precisely.",
                    "if_chosen": "The fix will optimize for visible UX correctness.",
                    "tradeoff": "May leave internal cleanup for later.",
                    "value": "user_visible",
                },
                {
                    "id": "B",
                    "title": "Contract-level correctness",
                    "proposal": "Fix the root contract and let UX behavior follow that contract.",
                    "if_chosen": "The solution will prioritize system invariants and future safety.",
                    "tradeoff": "May require broader changes.",
                    "value": "contract_level",
                },
            ],
        },
        "failing_scenario": {
            "prompt": "Which failing scenario should define the bugfix scope?",
            "options": [
                {
                    "id": "A",
                    "title": "Single concrete scenario",
                    "proposal": "Narrow the fix to one reproducible failing path.",
                    "if_chosen": "Verification stays focused and safer.",
                    "tradeoff": "Adjacent cases may remain unaddressed.",
                    "value": "single_case",
                },
                {
                    "id": "B",
                    "title": "Class of related scenarios",
                    "proposal": "Fix the entire class of failures around the same root cause.",
                    "if_chosen": "The patch will be more preventative.",
                    "tradeoff": "Higher risk of larger behavior changes.",
                    "value": "failure_class",
                },
            ],
        },
        "non_regression_boundary": {
            "prompt": "How strict should the non-regression boundary be?",
            "options": [
                {
                    "id": "A",
                    "title": "Tight boundary",
                    "proposal": "Preserve all adjacent existing behavior unless directly required.",
                    "if_chosen": "The patch stays narrow and predictable.",
                    "tradeoff": "Some cleanup opportunities are deferred.",
                    "value": "tight",
                },
                {
                    "id": "B",
                    "title": "Broader cleanup allowed",
                    "proposal": "Allow adjacent cleanup while fixing the bug.",
                    "if_chosen": "The code may emerge cleaner and easier to maintain.",
                    "tradeoff": "Higher regression risk.",
                    "value": "broader_cleanup",
                },
            ],
        },
        "verification_path": {
            "prompt": "What verification path should define done?",
            "options": [
                {
                    "id": "A",
                    "title": "Automated-first",
                    "proposal": "Require tests or deterministic checks to prove the fix.",
                    "if_chosen": "The implementation will prioritize repeatable evidence.",
                    "tradeoff": "May require more setup work.",
                    "value": "automated",
                },
                {
                    "id": "B",
                    "title": "Manual-first",
                    "proposal": "Allow manual verification if automation would be disproportionate.",
                    "if_chosen": "The fix can ship faster in constrained repos.",
                    "tradeoff": "Evidence is weaker and less reusable.",
                    "value": "manual",
                },
            ],
        },
    },
    "refactor": {
        "preserved_invariants": {
            "prompt": "What should be the primary invariant of this refactor?",
            "options": [
                {
                    "id": "A",
                    "title": "Zero behavior change",
                    "proposal": "Treat this as a pure structural refactor.",
                    "if_chosen": "Verification focuses on identical runtime behavior.",
                    "tradeoff": "Some improvements may be deferred.",
                    "value": "zero_behavior_change",
                },
                {
                    "id": "B",
                    "title": "Small safe improvements allowed",
                    "proposal": "Allow minor behavior improvements if they simplify the design.",
                    "if_chosen": "The refactor can clean up rough edges while restructuring.",
                    "tradeoff": "Acceptance criteria must be tighter.",
                    "value": "safe_improvements",
                },
            ],
        },
        "allowed_behavior_changes": {
            "prompt": "How broad can behavior changes be during the refactor?",
            "options": [
                {
                    "id": "A",
                    "title": "Strictly constrained",
                    "proposal": "Only change behavior where explicitly listed.",
                    "if_chosen": "Review risk stays lower.",
                    "tradeoff": "May require follow-up work later.",
                    "value": "strict",
                },
                {
                    "id": "B",
                    "title": "Adjacent changes allowed",
                    "proposal": "Permit adjacent behavior changes if they support the new structure.",
                    "if_chosen": "The end state can be more coherent.",
                    "tradeoff": "Needs stronger review and tests.",
                    "value": "adjacent_allowed",
                },
            ],
        },
        "scope_boundary": {
            "prompt": "How should the refactor scope be bounded?",
            "options": [
                {
                    "id": "A",
                    "title": "Module-local",
                    "proposal": "Keep the refactor inside the immediate module or subsystem.",
                    "if_chosen": "Implementation stays smaller and easier to review.",
                    "tradeoff": "Some duplication may remain outside the boundary.",
                    "value": "module_local",
                },
                {
                    "id": "B",
                    "title": "Cross-cutting",
                    "proposal": "Allow the refactor to span connected files and contracts.",
                    "if_chosen": "The resulting architecture can be cleaner end-to-end.",
                    "tradeoff": "Higher change surface and review burden.",
                    "value": "cross_cutting",
                },
            ],
        },
        "verification_path": {
            "prompt": "What verification standard should gate the refactor?",
            "options": [
                {
                    "id": "A",
                    "title": "Tests plus smoke verification",
                    "proposal": "Require automated checks and at least one end-to-end smoke path.",
                    "if_chosen": "Evidence quality is stronger.",
                    "tradeoff": "More time spent on verification.",
                    "value": "tests_plus_smoke",
                },
                {
                    "id": "B",
                    "title": "Existing tests only",
                    "proposal": "Rely on existing test coverage unless a new gap is obvious.",
                    "if_chosen": "Implementation moves faster.",
                    "tradeoff": "Some edge-case regressions may remain unobserved.",
                    "value": "existing_tests",
                },
            ],
        },
    },
    "docs": {
        "audience": {
            "prompt": "Who is the primary audience for this document?",
            "options": [
                {
                    "id": "A",
                    "title": "Operators or contributors",
                    "proposal": "Write for engineers who will use or maintain the workflow.",
                    "if_chosen": "Content will be practical and implementation-focused.",
                    "tradeoff": "Less introductory guidance for newcomers.",
                    "value": "contributors",
                },
                {
                    "id": "B",
                    "title": "New adopters",
                    "proposal": "Write for users approaching the system for the first time.",
                    "if_chosen": "Content will emphasize onboarding clarity.",
                    "tradeoff": "Less detail for internal maintainers.",
                    "value": "new_adopters",
                },
            ],
        },
        "artifact_type": {
            "prompt": "What artifact type should this documentation primarily be?",
            "options": [
                {
                    "id": "A",
                    "title": "Spec or contract",
                    "proposal": "Make this a normative specification with explicit rules.",
                    "if_chosen": "Implementation expectations become clearer.",
                    "tradeoff": "Less narrative explanation.",
                    "value": "spec",
                },
                {
                    "id": "B",
                    "title": "Guide or walkthrough",
                    "proposal": "Make this a practical usage guide.",
                    "if_chosen": "The doc becomes easier to follow step by step.",
                    "tradeoff": "Normative constraints may be softer.",
                    "value": "guide",
                },
            ],
        },
        "tone_format": {
            "prompt": "What tone or format should this documentation follow?",
            "options": [
                {
                    "id": "A",
                    "title": "Strict and canonical",
                    "proposal": "Use a compact, rule-driven format.",
                    "if_chosen": "The document becomes a clear source of truth.",
                    "tradeoff": "Less conversational explanation.",
                    "value": "canonical",
                },
                {
                    "id": "B",
                    "title": "Explanatory and practical",
                    "proposal": "Use a more guided narrative with rationale.",
                    "if_chosen": "Adoption can be easier.",
                    "tradeoff": "Hard rules may be less obvious at a glance.",
                    "value": "practical",
                },
            ],
        },
        "acceptance_boundary": {
            "prompt": "What should count as done for this documentation change?",
            "options": [
                {
                    "id": "A",
                    "title": "Text correctness only",
                    "proposal": "Treat accurate and aligned documentation as sufficient.",
                    "if_chosen": "Implementation can stay focused on content changes.",
                    "tradeoff": "Runtime validation may be deferred.",
                    "value": "text_only",
                },
                {
                    "id": "B",
                    "title": "Docs plus runtime alignment",
                    "proposal": "Require the docs and workflow behavior to match.",
                    "if_chosen": "The doc becomes more trustworthy as a contract.",
                    "tradeoff": "Requires broader changes.",
                    "value": "docs_plus_runtime",
                },
            ],
        },
    },
}

QUESTION_BANK["other"] = {
    "target_artifact": {
        "prompt": "What is the primary artifact this task should produce?",
        "options": [
            {
                "id": "A",
                "title": "Working implementation",
                "proposal": "Treat the output as a directly usable implementation artifact.",
                "if_chosen": "Acceptance will emphasize runnable or shippable output.",
                "tradeoff": "Planning must be more decision-complete.",
                "value": "implementation",
            },
            {
                "id": "B",
                "title": "Structured design artifact",
                "proposal": "Treat the output as a design or specification artifact.",
                "if_chosen": "Acceptance will emphasize clarity and completeness.",
                "tradeoff": "Execution is deferred.",
                "value": "design",
            },
        ],
    },
    "expected_outcome": {
        "prompt": "What should define success for this task?",
        "options": [
            {
                "id": "A",
                "title": "Concrete deliverable",
                "proposal": "Define success by a concrete artifact or behavior.",
                "if_chosen": "Verification becomes more operational.",
                "tradeoff": "May force earlier decisions.",
                "value": "concrete_deliverable",
            },
            {
                "id": "B",
                "title": "Exploration plus recommendation",
                "proposal": "Define success by research and a recommended direction.",
                "if_chosen": "The workflow can stay more open-ended.",
                "tradeoff": "Execution readiness will stay lower.",
                "value": "exploration",
            },
        ],
    },
    "scope_boundary": QUESTION_BANK["refactor"]["scope_boundary"],
    "constraints": {
        "prompt": "What should be treated as the primary constraint?",
        "options": [
            {
                "id": "A",
                "title": "Speed and minimal change",
                "proposal": "Optimize for the smallest safe change set.",
                "if_chosen": "The workflow will bias toward narrow scope.",
                "tradeoff": "May defer broader improvements.",
                "value": "minimal_change",
            },
            {
                "id": "B",
                "title": "Quality and completeness",
                "proposal": "Optimize for the most complete correct outcome within scope.",
                "if_chosen": "The workflow can take broader corrective action.",
                "tradeoff": "Higher implementation cost.",
                "value": "quality_first",
            },
        ],
    },
    "success_criteria": {
        "prompt": "How explicit should success criteria be before execution?",
        "options": [
            {
                "id": "A",
                "title": "Strict acceptance list",
                "proposal": "Require an explicit checklist before execution.",
                "if_chosen": "Approval quality improves.",
                "tradeoff": "More upfront discussion.",
                "value": "strict_checklist",
            },
            {
                "id": "B",
                "title": "Flexible outcome framing",
                "proposal": "Allow broader success framing if the task is exploratory.",
                "if_chosen": "The workflow stays more adaptive.",
                "tradeoff": "Readiness may stay lower for longer.",
                "value": "flexible",
            },
        ],
    },
}

PRESSURE_PASS_QUESTION = {
    "id": "Q_PRESSURE",
    "decision_key": "pressure_pass",
    "prompt": "Pressure pass: which challenge should be locked in before execution?",
    "options": [
        {
            "id": "A",
            "title": "Tighten acceptance and contradiction handling",
            "proposal": "Require explicit acceptance boundaries and contradiction resolution before run.",
            "if_chosen": "The workflow will prioritize defensible execution criteria.",
            "tradeoff": "More upfront rigor before implementation starts.",
            "value": "tighten_acceptance",
        },
        {
            "id": "B",
            "title": "Narrow scope to reduce ambiguity",
            "proposal": "Shrink scope if any unresolved tension remains in acceptance or boundaries.",
            "if_chosen": "The workflow will reduce risk by executing a tighter slice.",
            "tradeoff": "The first implementation may be smaller than the initial ambition.",
            "value": "narrow_scope",
        },
    ],
    "reply_format": "Choose: A | B\nOptional note: ...",
}


class RalphRuntimeError(RuntimeError):
    """User-facing runtime failure."""


@dataclass
class CommandResult:
    args: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "args": self.args,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class TerminalRunVisualizer:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.story_id = "-"
        self.story_title = "idle"

    def begin_story(self, story: dict[str, Any]) -> None:
        self.story_id = story["id"]
        self.story_title = story["title"]
        self.stage("run", f"Starting story {self.story_id} {self.story_title}")

    def stage(self, stage: str, message: str) -> None:
        if not self.enabled:
            return
        block = "\n".join(
            [
                "Ralph Run Monitor",
                f"Story: {self.story_id} {self.story_title}",
                f"Stage: {stage}",
                f"Note: {message}",
                "",
            ]
        )
        sys.stdout.write(block)
        sys.stdout.flush()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_path_from_args(repo: str | None) -> Path:
    candidate = repo or os.environ.get("TARGET_REPO") or os.getcwd()
    return Path(candidate).expanduser().resolve()


def state_dir(repo_path: Path) -> Path:
    return repo_path / ".codex-ralph"


def config_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "config.json"


def state_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "state.json"


def goal_spec_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "goal_spec.json"


def plan_score_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "plan_score.json"


def scorecard_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "scorecard.json"


def task_graph_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "task_graph.json"


def integration_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "integration.json"


def events_path(repo_path: Path) -> Path:
    return state_dir(repo_path) / "events.jsonl"


def runs_dir(repo_path: Path) -> Path:
    path = state_dir(repo_path) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_dir(repo_path: Path, run_id: str) -> Path:
    path = runs_dir(repo_path) / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_artifact_dir(repo_path: Path, run_id: str, task_id: str) -> Path:
    path = run_dir(repo_path, run_id) / "tasks" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def batches_dir(repo_path: Path, run_id: str) -> Path:
    path = run_dir(repo_path, run_id) / "batches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def worktrees_dir(repo_path: Path) -> Path:
    path = state_dir(repo_path) / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_worktree_path(repo_path: Path, run_id: str, task_id: str) -> Path:
    return worktrees_dir(repo_path) / run_id / task_id


def playwright_dir(repo_path: Path) -> Path:
    path = state_dir(repo_path) / "playwright"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_repo_state_dir(repo_path: Path) -> None:
    state_dir(repo_path).mkdir(parents=True, exist_ok=True)
    runs_dir(repo_path)
    worktrees_dir(repo_path)
    playwright_dir(repo_path)


def read_json(path: Path, *, required: bool = True) -> Any:
    if not path.exists():
        if required:
            raise RalphRuntimeError(f"Missing required JSON file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RalphRuntimeError(f"Invalid JSON: {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_event(
    repo_path: Path,
    *,
    stage: str,
    status: str,
    message: str,
    run_id: str | None = None,
    story_id: str | None = None,
    artifact: str | None = None,
    next_stage: str | None = None,
) -> dict[str, Any]:
    payload = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "stage": stage,
        "story_id": story_id,
        "status": status,
        "message": message,
        "artifact": artifact,
        "next": next_stage,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    path = events_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def load_events(repo_path: Path) -> list[dict[str, Any]]:
    path = events_path(repo_path)
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def repo_is_git(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_writable_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    if not repo_path.is_dir():
        raise RalphRuntimeError(f"Target repo is not a directory: {repo_path}")
    ensure_repo_state_dir(repo_path)
    probe = state_dir(repo_path) / ".write-probe"
    try:
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RalphRuntimeError(f"Target repo is not writable: {repo_path}") from exc


def schema_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, int):
        return "integer"
    return type(value).__name__


def validate_schema_value(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise RalphRuntimeError(f"{path} expected object, got {schema_type_name(value)}")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise RalphRuntimeError(f"{path} missing required field `{key}`")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise RalphRuntimeError(f"{path} has unsupported fields: {', '.join(extra)}")
        for key, child_schema in properties.items():
            if key in value:
                validate_schema_value(value[key], child_schema, path=f"{path}.{key}")
        return

    if expected_type == "array":
        if not isinstance(value, list):
            raise RalphRuntimeError(f"{path} expected array, got {schema_type_name(value)}")
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            raise RalphRuntimeError(f"{path} expected at least {min_items} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema_value(item, item_schema, path=f"{path}[{index}]")
        return

    if expected_type == "string" and not isinstance(value, str):
        raise RalphRuntimeError(f"{path} expected string, got {schema_type_name(value)}")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise RalphRuntimeError(f"{path} expected boolean, got {schema_type_name(value)}")
    if expected_type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        raise RalphRuntimeError(f"{path} expected integer, got {schema_type_name(value)}")

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        allowed = ", ".join(repr(item) for item in enum_values)
        raise RalphRuntimeError(f"{path} expected one of {allowed}, got {value!r}")


def validate_payload_against_schema(payload: Any, schema_path: Path) -> None:
    schema = read_json(schema_path)
    if not isinstance(schema, dict):
        raise RalphRuntimeError(f"Schema is not an object: {schema_path}")
    validate_schema_value(payload, schema)


def require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RalphRuntimeError(f"Missing non-empty `{key}`")
    return value.strip()


def require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise RalphRuntimeError(f"Missing non-empty `{key}`")
    result = [str(item).strip() for item in value if str(item).strip()]
    if len(result) != len(value):
        raise RalphRuntimeError(f"`{key}` must contain only non-empty strings")
    return result


def normalize_codebase_evidence(payload: dict[str, Any]) -> list[dict[str, str]]:
    evidence = payload.get("codebase_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise RalphRuntimeError("Missing non-empty `codebase_evidence`")
    result: list[dict[str, str]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise RalphRuntimeError(f"codebase_evidence[{index}] must be an object")
        result.append(
            {
                "claim": require_text(item, "claim"),
                "file": require_text(item, "file"),
                "lines": require_text(item, "lines"),
            }
        )
    return result


def normalize_risks(payload: dict[str, Any]) -> list[dict[str, str]]:
    risks = payload.get("risks")
    if not isinstance(risks, list) or not risks:
        raise RalphRuntimeError("Missing non-empty `risks`")
    result: list[dict[str, str]] = []
    for index, item in enumerate(risks):
        if not isinstance(item, dict):
            raise RalphRuntimeError(f"risks[{index}] must be an object")
        result.append(
            {
                "risk": require_text(item, "risk"),
                "mitigation": require_text(item, "mitigation"),
            }
        )
    return result


def is_ui_or_browser_task(text: str, verification: list[str] | None = None) -> bool:
    haystack = " ".join([text, *(verification or [])]).lower()
    markers = [
        "ui",
        "frontend",
        "browser",
        "web",
        "网页",
        "前端",
        "页面",
        "canvas",
        "three.js",
        "3d",
        "playwright",
        "screenshot",
        "visual",
        "interaction",
        "交互",
        "可视化",
        "游戏",
    ]
    return any(marker in haystack for marker in markers)


def normalize_story(raw_story: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw_story, dict):
        raise RalphRuntimeError("Each story must be an object")
    story_id = str(raw_story.get("id") or f"S{index}").strip()
    title = str(raw_story.get("title") or raw_story.get("goal") or story_id).strip()
    description = str(raw_story.get("description") or raw_story.get("goal") or title).strip()
    acceptance_criteria = raw_story.get("acceptance_criteria") or raw_story.get("acceptanceCriteria") or []
    suggested_tests = raw_story.get("suggested_tests") or raw_story.get("verification") or []
    dependencies = raw_story.get("dependencies") or []
    if not isinstance(acceptance_criteria, list) or not acceptance_criteria:
        raise RalphRuntimeError(f"Story `{story_id}` requires non-empty acceptance_criteria")
    if not isinstance(suggested_tests, list) or not suggested_tests:
        suggested_tests = ["manual verification required"]
    if not isinstance(dependencies, list):
        raise RalphRuntimeError(f"Story `{story_id}` dependencies must be an array")
    return {
        "id": story_id,
        "title": title,
        "description": description,
        "acceptance_criteria": [str(item).strip() for item in acceptance_criteria if str(item).strip()],
        "suggested_tests": [str(item).strip() for item in suggested_tests if str(item).strip()],
        "dependencies": [str(item).strip() for item in dependencies if str(item).strip()],
        "allowed_scope": [str(item).strip() for item in raw_story.get("allowed_scope", []) if str(item).strip()] if isinstance(raw_story.get("allowed_scope", []), list) else [],
        "forbidden_scope": [str(item).strip() for item in raw_story.get("forbidden_scope", []) if str(item).strip()] if isinstance(raw_story.get("forbidden_scope", []), list) else [],
        "requires_playwright": bool(raw_story.get("requires_playwright", False)),
        "batch": raw_story.get("batch"),
        "status": "passed" if bool(raw_story.get("passes")) else "pending",
        "attempt_count": int(raw_story.get("attempt_count", 0)),
        "rework_attempt_count": int(raw_story.get("rework_attempt_count", 0)),
        "max_rework_attempts": int(raw_story.get("max_rework_attempts", MAX_REWORK_ATTEMPTS)),
        "last_run_id": raw_story.get("last_run_id"),
        "worktree": raw_story.get("worktree"),
        "branch": raw_story.get("branch"),
        "remaining_work": [str(item).strip() for item in raw_story.get("remaining_work", []) if str(item).strip()],
        "last_review_reason": str(raw_story.get("last_review_reason", "")).strip(),
        "review": raw_story.get("review") if isinstance(raw_story.get("review"), dict) else None,
        "rework_history": raw_story.get("rework_history", []) if isinstance(raw_story.get("rework_history", []), list) else [],
    }


def stories_from_goal_spec(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stories = payload.get("stories")
    if stories is None:
        return [
            {
                "id": "S1",
                "title": payload.get("title") or require_text(payload, "goal")[:80],
                "description": require_text(payload, "goal"),
                "acceptance_criteria": require_string_list(payload, "acceptance_criteria"),
                "suggested_tests": require_string_list(payload, "verification"),
                "dependencies": [],
                "allowed_scope": require_string_list(payload, "allowed_scope"),
                "forbidden_scope": require_string_list(payload, "forbidden_scope"),
                "requires_playwright": is_ui_or_browser_task(require_text(payload, "goal"), require_string_list(payload, "verification")),
                "batch": None,
                "status": "pending",
                "attempt_count": 0,
                "rework_attempt_count": 0,
                "max_rework_attempts": MAX_REWORK_ATTEMPTS,
                "last_run_id": None,
                "worktree": None,
                "branch": None,
                "remaining_work": [],
                "last_review_reason": "",
                "review": None,
                "rework_history": [],
            }
        ]
    if not isinstance(stories, list) or not stories:
        raise RalphRuntimeError("GoalSpec `stories` must be a non-empty array")
    return [normalize_story(story, index) for index, story in enumerate(stories, start=1)]


def validate_story_graph(stories: list[dict[str, Any]]) -> None:
    story_map = {story["id"]: story for story in stories}
    if len(story_map) != len(stories):
        raise RalphRuntimeError("Duplicate story ids are not allowed")
    for story in stories:
        status = story.get("status")
        if status not in STORY_STATUSES:
            raise RalphRuntimeError(f"Unsupported story status `{status}`")
        for dependency in story["dependencies"]:
            if dependency not in story_map:
                raise RalphRuntimeError(f"Story `{story['id']}` references missing dependency `{dependency}`")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(story_id: str) -> None:
        if story_id in visited:
            return
        if story_id in visiting:
            raise RalphRuntimeError(f"Cycle detected at story `{story_id}`")
        visiting.add(story_id)
        for dependency in story_map[story_id]["dependencies"]:
            visit(dependency)
        visiting.remove(story_id)
        visited.add(story_id)

    for story_id in story_map:
        visit(story_id)


def normalize_task_graph(payload: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    tasks_raw = payload.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise RalphRuntimeError("task_graph.json requires a non-empty `tasks` array")

    tasks: list[dict[str, Any]] = []
    for index, raw_task in enumerate(tasks_raw, start=1):
        if not isinstance(raw_task, dict):
            raise RalphRuntimeError("Each task graph task must be an object")
        task_id = str(raw_task.get("task_id") or raw_task.get("id") or f"T{index}").strip()
        title = str(raw_task.get("title") or raw_task.get("goal") or task_id).strip()
        description = str(raw_task.get("description") or raw_task.get("goal") or title).strip()
        dependencies = raw_task.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise RalphRuntimeError(f"Task `{task_id}` dependencies must be an array")
        acceptance = raw_task.get("acceptance_criteria") or raw_task.get("acceptanceCriteria") or []
        if not isinstance(acceptance, list) or not acceptance:
            raise RalphRuntimeError(f"Task `{task_id}` requires non-empty acceptance_criteria")
        verification = raw_task.get("verification") or raw_task.get("suggested_tests") or []
        if not isinstance(verification, list):
            raise RalphRuntimeError(f"Task `{task_id}` verification must be an array")
        allowed_scope = raw_task.get("allowed_scope", [])
        forbidden_scope = raw_task.get("forbidden_scope", [])
        if not isinstance(allowed_scope, list):
            raise RalphRuntimeError(f"Task `{task_id}` allowed_scope must be an array")
        if not isinstance(forbidden_scope, list):
            raise RalphRuntimeError(f"Task `{task_id}` forbidden_scope must be an array")
        requires_playwright = bool(raw_task.get("requires_playwright", is_ui_or_browser_task(description, [str(item) for item in verification])))
        tasks.append(
            {
                "task_id": task_id,
                "id": task_id,
                "title": title,
                "description": description,
                "dependencies": [str(item).strip() for item in dependencies if str(item).strip()],
                "allowed_scope": [str(item).strip() for item in allowed_scope if str(item).strip()],
                "forbidden_scope": [str(item).strip() for item in forbidden_scope if str(item).strip()],
                "acceptance_criteria": [str(item).strip() for item in acceptance if str(item).strip()],
                "verification": [str(item).strip() for item in verification if str(item).strip()],
                "requires_playwright": requires_playwright,
                "status": str(raw_task.get("status", "pending")).strip() or "pending",
                "parallel_group": raw_task.get("parallel_group"),
                "rework_attempt_count": int(raw_task.get("rework_attempt_count", 0)),
                "max_rework_attempts": int(raw_task.get("max_rework_attempts", MAX_REWORK_ATTEMPTS)),
                "worktree": raw_task.get("worktree"),
                "branch": raw_task.get("branch"),
                "review": raw_task.get("review") if isinstance(raw_task.get("review"), dict) else None,
                "rework_history": raw_task.get("rework_history", []) if isinstance(raw_task.get("rework_history", []), list) else [],
            }
        )

    story_like = [
        {
            "id": task["task_id"],
            "dependencies": task["dependencies"],
            "status": task["status"] if task["status"] in STORY_STATUSES else "pending",
        }
        for task in tasks
    ]
    validate_story_graph(story_like)

    batches = compute_task_batches(tasks)
    return {
        "version": "v10",
        "run_id": str(payload.get("run_id") or utc_stamp()).strip(),
        "approval_required": bool(payload.get("approval_required", True)),
        "approved": bool(payload.get("approved", False)),
        "summary": str(payload.get("summary") or (state or {}).get("goal") or "").strip(),
        "tasks": tasks,
        "batches": batches,
    }


def compute_task_batches(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = {task["task_id"] for task in tasks}
    completed: set[str] = set()
    task_map = {task["task_id"]: task for task in tasks}
    batches: list[dict[str, Any]] = []
    while remaining:
        ready = sorted(
            task_id
            for task_id in remaining
            if all(dependency in completed for dependency in task_map[task_id]["dependencies"])
        )
        if not ready:
            raise RalphRuntimeError("Task graph contains an unresolved dependency cycle")
        batches.append({"batch_id": f"B{len(batches) + 1}", "tasks": ready, "parallel": len(ready) > 1})
        completed.update(ready)
        remaining.difference_update(ready)
    return batches


def load_task_graph(repo_path: Path, *, required: bool = True) -> dict[str, Any] | None:
    payload = read_json(task_graph_path(repo_path), required=required)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RalphRuntimeError("task_graph.json must be an object")
    return payload


def save_task_graph(repo_path: Path, task_graph: dict[str, Any]) -> None:
    write_json(task_graph_path(repo_path), task_graph)


def find_task(task_graph: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in task_graph.get("tasks", []):
        if isinstance(task, dict) and str(task.get("task_id")) == task_id:
            return task
    raise RalphRuntimeError(f"Task `{task_id}` was not found in task_graph.json")


def review_queue_from_task_graph(task_graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(task_graph, dict):
        return []
    queue: list[dict[str, Any]] = []
    for task in task_graph.get("tasks", []):
        if isinstance(task, dict) and task.get("status") in {"worker_done", "review_required", "rework_pending"}:
            queue.append({"task_id": task.get("task_id"), "title": task.get("title"), "status": task.get("status")})
    return queue


def build_config_payload(
    repo_path: Path,
    *,
    allow_non_git: bool,
    claude_model: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    return {
        "skill_root": str(SKILL_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "repo_path": str(repo_path),
        "require_git": not allow_non_git,
        "claude_model": claude_model,
        "timeout_seconds": timeout_seconds,
    }


def infer_task_archetype(goal_text: str) -> str:
    lowered = goal_text.lower()
    if any(token in lowered for token in ("game", "page", "ui", "web", "screen", "layout", "canvas")):
        return "feature_ui"
    if any(token in lowered for token in ("fix", "bug", "issue", "broken", "error", "regression")):
        return "bugfix"
    if any(token in lowered for token in ("refactor", "cleanup", "restructure", "simplify")):
        return "refactor"
    if any(token in lowered for token in ("readme", "doc", "documentation", "guide", "spec")):
        return "docs"
    return "other"


def normalized_history(raw_history: Any) -> list[dict[str, str]]:
    if not isinstance(raw_history, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        entry = {
            "id": str(item.get("id", "")).strip(),
            "prompt": str(item.get("prompt", "")).strip(),
            "selected_option": str(item.get("selected_option", "")).strip(),
            "user_note": str(item.get("user_note", "")).strip(),
            "resolved_decision_key": str(item.get("resolved_decision_key", "")).strip(),
            "language": normalize_language_code(item.get("language")),
        }
        if entry["id"] and entry["resolved_decision_key"]:
            result.append(entry)
    return result


def normalized_resolved_decisions(raw_resolved: Any) -> dict[str, str]:
    if not isinstance(raw_resolved, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw_resolved.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def normalize_language_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return ""


def detect_language(text: str) -> str:
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return ""


def pick_language(*candidates: Any) -> str:
    for candidate in candidates:
        normalized = normalize_language_code(candidate)
        if normalized:
            return normalized
        if isinstance(candidate, str):
            detected = detect_language(candidate)
            if detected:
                return detected
    return "en"


def copy_for(language: str) -> dict[str, str]:
    return SYSTEM_COPY["zh" if language == "zh" else "en"]


def localized_decision_label(decision_key: str, language: str) -> str:
    if language == "zh":
        return DECISION_LABELS_ZH.get(decision_key, DECISION_LABELS.get(decision_key, decision_key))
    return DECISION_LABELS.get(decision_key, decision_key)


def localize_option_fields(option: dict[str, Any], decision_key: str, language: str) -> dict[str, Any]:
    localized = dict(option)
    if language != "zh":
        return localized
    override = QUESTION_COPY_ZH.get(decision_key, {}).get("options", {}).get(str(option.get("id", "")).strip())
    if not override:
        return localized
    for field in ("title", "proposal", "if_chosen", "tradeoff"):
        value = override.get(field)
        if isinstance(value, str) and value.strip():
            localized[field] = value.strip()
    return localized


def build_question(archetype: str, decision_key: str, *, round_number: int) -> dict[str, Any]:
    if decision_key == "pressure_pass":
        return {
            "id": f"Q{round_number}",
            "decision_key": "pressure_pass",
            "prompt": PRESSURE_PASS_QUESTION["prompt"],
            "options": [dict(option) for option in PRESSURE_PASS_QUESTION["options"]],
            "reply_format": PRESSURE_PASS_QUESTION["reply_format"],
        }
    question = QUESTION_BANK.get(archetype, QUESTION_BANK["other"]).get(decision_key)
    if question is None:
        fallback = QUESTION_BANK["other"].get(decision_key)
        if fallback is None:
            raise RalphRuntimeError(f"Missing question template for {archetype}:{decision_key}")
        question = fallback
    return {
        "id": f"Q{round_number}",
        "decision_key": decision_key,
        "prompt": str(question["prompt"]),
        "options": [dict(option) for option in question["options"]],
        "reply_format": "Choose: A | B\nOptional note: ...",
    }


def localize_question(question: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    if not isinstance(question, dict):
        return None
    localized = dict(question)
    decision_key = str(question.get("decision_key", "")).strip()
    if language == "zh":
        prompt = QUESTION_COPY_ZH.get(decision_key, {}).get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            localized["prompt"] = prompt.strip()
        localized["reply_format"] = "选择：A | B\n可选备注：..."
    options = []
    for option in question.get("options", []):
        if isinstance(option, dict):
            options.append(localize_option_fields(option, decision_key, language))
    localized["options"] = options
    return localized


def localize_discussion_summary(summary: str, language: str) -> str:
    text = str(summary or "").strip()
    if language != "zh" or not text:
        return text
    if text == "The repository is grounded, but the request is still too ambiguous to execute. Key gameplay, controls, victory rules, and presentation details are missing.":
        return "仓库已有可落地的页面骨架，但当前需求仍不足以直接执行。关键玩法、控制方式、胜负规则和表现细节都还没有定清。"
    if text == "Discussion is still required before execution. Key decisions remain unresolved.":
        return "执行前仍需继续讨论，关键决策尚未收敛。"
    if text == "Discussion is complete and the workflow is ready for final approval.":
        return "讨论已完成，工作流可以进入最终确认。"
    if text == "The request is still too ambiguous to execute.":
        return "当前需求仍然过于模糊，暂时不能直接执行。"
    return text


def localize_goal_text(goal: str, language: str) -> str:
    text = str(goal or "").strip()
    if language != "zh" or not text:
        return text
    if text == "Build a browser-based single-page game titled 黑洞吞建筑成长，人机竞赛 where the player controls a growing black hole and competes against an AI rival to swallow buildings on the same map.":
        return "制作一个浏览器单页网页小游戏《黑洞吞建筑成长，人机竞赛》：玩家控制不断成长的黑洞，与 AI 对手在同一张地图上争夺并吞噬建筑。"
    return text


def localize_label_list(items: list[Any], language: str) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if language == "zh":
            matched_key = next((key for key, value in DECISION_LABELS.items() if value == text), None)
            if matched_key:
                result.append(localized_decision_label(matched_key, language))
                continue
        result.append(text)
    return result


def build_discussion_state(goal_spec: dict[str, Any]) -> dict[str, Any]:
    goal_text = require_text(goal_spec, "goal")
    raw_discussion = goal_spec.get("discussion", {})
    if raw_discussion is not None and not isinstance(raw_discussion, dict):
        raise RalphRuntimeError("GoalSpec `discussion` must be an object")
    raw_discussion = raw_discussion or {}

    archetype = str(raw_discussion.get("task_archetype") or infer_task_archetype(goal_text)).strip()
    if archetype not in TASK_DECISION_CHECKLISTS:
        archetype = "other"
    required_decisions = TASK_DECISION_CHECKLISTS[archetype]
    resolved_decisions = normalized_resolved_decisions(raw_discussion.get("resolved_decisions", {}))
    history = normalized_history(raw_discussion.get("history", []))
    pressure_pass_completed = bool(raw_discussion.get("pressure_pass_completed", False))
    unresolved = [key for key in required_decisions if not resolved_decisions.get(key)]

    if unresolved:
        current_question = build_question(archetype, unresolved[0], round_number=len(history) + 1)
        open_questions = [str(build_question(archetype, key, round_number=len(history) + 1)["prompt"]) for key in unresolved]
        missing_decisions = [DECISION_LABELS.get(key, key) for key in unresolved]
        status = "needs_discussion"
    elif not pressure_pass_completed:
        current_question = build_question(archetype, "pressure_pass", round_number=len(history) + 1)
        open_questions = [current_question["prompt"]]
        missing_decisions = [DECISION_LABELS["pressure_pass"]]
        status = "needs_discussion"
    else:
        current_question = None
        open_questions = []
        missing_decisions = []
        status = "ready"

    discussion_ready = status == "ready"
    round_number = int(raw_discussion.get("round", max(1, len(history) + (0 if discussion_ready else 1))))
    conversation_language = pick_language(
        goal_spec.get("conversation_language"),
        goal_spec.get("last_explicit_language"),
        raw_discussion.get("last_explicit_language"),
        goal_text,
    )
    summary = str(
        raw_discussion.get("summary")
        or goal_spec.get("discussion_summary")
        or (
            copy_for(conversation_language)["discussion_ready"]
            if discussion_ready
            else copy_for(conversation_language)["discussion_blocked"]
        )
    ).strip()

    return {
        "mode": "deep_interview",
        "round": round_number,
        "status": status,
        "task_archetype": archetype,
        "required_decisions": required_decisions,
        "current_question": current_question,
        "history": history,
        "resolved_decisions": resolved_decisions,
        "pressure_pass_completed": pressure_pass_completed,
        "open_questions": open_questions,
        "missing_decisions": missing_decisions,
        "ready": discussion_ready,
        "summary": localize_discussion_summary(summary, conversation_language),
        "conversation_language": conversation_language,
        "last_explicit_language": pick_language(
            goal_spec.get("last_explicit_language"),
            raw_discussion.get("last_explicit_language"),
            conversation_language,
        ),
    }


def average_score(values: dict[str, int]) -> int:
    if not values:
        return 0
    return round(sum(values.values()) / len(values))


def conservative_total(raw_total: Any, computed_total: int) -> int:
    if isinstance(raw_total, int):
        return min(raw_total, computed_total)
    return computed_total


def merge_hard_blockers(computed: list[str], raw: Any, *, allow_raw_merge: bool) -> list[str]:
    merged: list[str] = []
    for item in computed:
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
    if allow_raw_merge and isinstance(raw, list):
        for item in raw:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def build_scorecard(goal_spec: dict[str, Any], raw_score: dict[str, Any] | None = None) -> dict[str, Any]:
    discussion = build_discussion_state(goal_spec)
    evidence_count = len(normalize_codebase_evidence(goal_spec))
    acceptance_count = len(require_string_list(goal_spec, "acceptance_criteria"))
    verification_count = len(require_string_list(goal_spec, "verification"))
    risks_count = len(normalize_risks(goal_spec))
    allowed_count = len(require_string_list(goal_spec, "allowed_scope"))
    forbidden_count = len(require_string_list(goal_spec, "forbidden_scope"))
    resolved_count = len(discussion["resolved_decisions"])
    total_required = len(discussion["required_decisions"])
    resolution_ratio = resolved_count / total_required if total_required else 1.0
    pressure_pass_completed = bool(discussion["pressure_pass_completed"])
    history_count = len(discussion["history"])

    epistemic_dimensions = {
        "intent_clarity": min(100, 55 + round(resolution_ratio * 45)),
        "outcome_clarity": min(100, 35 + acceptance_count * 15),
        "scope_clarity": min(100, 40 + min(allowed_count, 3) * 15 + min(forbidden_count, 3) * 10),
        "constraints_clarity": min(100, 35 + min(risks_count, 3) * 20),
        "success_criteria_clarity": min(100, 30 + acceptance_count * 12 + verification_count * 10),
        "codebase_grounding": min(100, 35 + evidence_count * 20),
    }
    deontic_dimensions = {
        "allowed_scope_explicitness": min(100, 50 + allowed_count * 15),
        "forbidden_scope_explicitness": min(100, 50 + forbidden_count * 15),
        "non_goals_explicitness": 100 if forbidden_count >= 2 else 60 if forbidden_count >= 1 else 20,
        "decision_boundaries_explicitness": min(100, round(resolution_ratio * 100)),
        "approval_boundary_clarity": 100 if isinstance(goal_spec.get("user_confirmation"), bool) else 0,
    }
    dialectical_dimensions = {
        "pressure_pass_completed": 100 if pressure_pass_completed else 0,
        "alternatives_examined": min(100, history_count * 25),
        "contradiction_check": 100 if pressure_pass_completed else (55 if resolution_ratio == 1.0 else 20),
        "failure_mode_coverage": min(100, 25 + risks_count * 25),
    }

    epistemic_blockers: list[str] = []
    if resolution_ratio < 1.0:
        epistemic_blockers.append("required decisions remain unresolved")
    if acceptance_count < 2:
        epistemic_blockers.append("acceptance criteria are too thin")
    if evidence_count < 1:
        epistemic_blockers.append("codebase grounding is missing")

    deontic_blockers: list[str] = []
    if allowed_count < 1:
        deontic_blockers.append("allowed scope is missing")
    if forbidden_count < 1:
        deontic_blockers.append("forbidden scope is missing")
    if resolution_ratio < 1.0:
        deontic_blockers.append("decision boundaries are incomplete")

    dialectical_blockers: list[str] = []
    if history_count < 1:
        dialectical_blockers.append("discussion history is empty")
    if not pressure_pass_completed:
        dialectical_blockers.append("pressure pass not completed")

    gates = {
        "epistemic": {
            "score": average_score(epistemic_dimensions),
            "threshold": GATE_THRESHOLDS["epistemic"],
            "passed": False,
            "blockers": epistemic_blockers,
            "dimensions": epistemic_dimensions,
        },
        "deontic": {
            "score": average_score(deontic_dimensions),
            "threshold": GATE_THRESHOLDS["deontic"],
            "passed": False,
            "blockers": deontic_blockers,
            "dimensions": deontic_dimensions,
        },
        "dialectical": {
            "score": average_score(dialectical_dimensions),
            "threshold": GATE_THRESHOLDS["dialectical"],
            "passed": False,
            "blockers": dialectical_blockers,
            "dimensions": dialectical_dimensions,
        },
    }

    for gate in gates.values():
        gate["passed"] = gate["score"] >= int(gate["threshold"]) and not gate["blockers"]

    computed_total = round(
        gates["epistemic"]["score"] * 0.40
        + gates["deontic"]["score"] * 0.35
        + gates["dialectical"]["score"] * 0.25
    )
    discussion_ready = bool(discussion["ready"])
    if not discussion_ready:
        computed_total = min(computed_total, 84)

    computed_hard_blockers = (
        [DECISION_LABELS.get(key, key) for key in discussion["required_decisions"] if not discussion["resolved_decisions"].get(key)]
        + gates["epistemic"]["blockers"]
        + gates["deontic"]["blockers"]
        + gates["dialectical"]["blockers"]
    )
    raw_hard_blockers = raw_score.get("hard_blockers") if isinstance(raw_score, dict) else None
    stale_raw_score = bool(discussion_ready and not computed_hard_blockers and isinstance(raw_hard_blockers, list) and any(str(item).strip() for item in raw_hard_blockers))
    total = computed_total if stale_raw_score else conservative_total(raw_score.get("total") if isinstance(raw_score, dict) else None, computed_total)
    hard_blockers = merge_hard_blockers(
        computed_hard_blockers,
        raw_hard_blockers,
        allow_raw_merge=not discussion_ready,
    )

    dimensions = {
        **epistemic_dimensions,
        **deontic_dimensions,
        **dialectical_dimensions,
    }
    decision = (
        "approved"
        if discussion_ready
        and total >= PLAN_THRESHOLD
        and all(gate["passed"] for gate in gates.values())
        and not hard_blockers
        else "blocked"
    )

    return {
        "total": total,
        "decision": decision,
        "threshold": PLAN_THRESHOLD,
        "discussion_ready": discussion_ready,
        "hard_blockers": hard_blockers,
        "dimensions": dimensions,
        "gates": gates,
    }


def canonicalize_goal_spec(goal_spec: dict[str, Any], raw_score: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(goal_spec)
    discussion = build_discussion_state(payload)
    payload["discussion_ready"] = bool(discussion["ready"])
    payload["discussion_summary"] = discussion["summary"]
    payload["open_questions"] = discussion["open_questions"]
    payload["missing_decisions"] = discussion["missing_decisions"]
    payload["user_confirmation"] = bool(payload.get("user_confirmation", False))
    payload["conversation_language"] = discussion["conversation_language"]
    payload["last_explicit_language"] = discussion["last_explicit_language"]
    payload["discussion"] = {
        "mode": "deep_interview",
        "round": discussion["round"],
        "status": discussion["status"],
        "task_archetype": discussion["task_archetype"],
        "current_question": discussion["current_question"],
        "history": discussion["history"],
        "resolved_decisions": discussion["resolved_decisions"],
        "pressure_pass_completed": discussion["pressure_pass_completed"],
        "last_explicit_language": discussion["last_explicit_language"],
    }
    scorecard = build_scorecard(payload, raw_score)
    payload["plan_score"] = scorecard
    payload["scorecard"] = scorecard
    return payload


def build_state_payload(goal_spec: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
    stories = stories_from_goal_spec(goal_spec)
    validate_story_graph(stories)
    discussion = build_discussion_state(goal_spec)
    copy = copy_for(discussion["conversation_language"])
    if not discussion["ready"]:
        stage = "discussion"
        status = "blocked"
        message = copy["status_discussion_blocked"]
        next_action = "answer_current_question" if discussion.get("current_question") else "continue_discussion"
    elif scorecard["decision"] != "approved":
        stage = "plan_gate"
        status = "blocked"
        message = copy["status_plan_gate_blocked"]
        next_action = "review_scorecard"
    elif not bool(goal_spec.get("user_confirmation", False)):
        stage = "approval_pending"
        status = "blocked"
        message = copy["status_approval_required"]
        next_action = "confirm_run"
    else:
        stage = "init"
        status = "passed"
        message = copy["status_initialized"]
        next_action = "wait_for_worker"
    return {
        "project_name": require_text(goal_spec, "project_name"),
        "branch_name": require_text(goal_spec, "branch_name"),
        "goal": require_text(goal_spec, "goal"),
        "allowed_scope": require_string_list(goal_spec, "allowed_scope"),
        "forbidden_scope": require_string_list(goal_spec, "forbidden_scope"),
        "codebase_evidence": normalize_codebase_evidence(goal_spec),
        "acceptance_criteria": require_string_list(goal_spec, "acceptance_criteria"),
        "verification": require_string_list(goal_spec, "verification"),
        "risks": normalize_risks(goal_spec),
        "discussion_ready": bool(goal_spec.get("discussion_ready", False)),
        "discussion_summary": str(goal_spec.get("discussion_summary", "")).strip(),
        "open_questions": [str(item).strip() for item in goal_spec.get("open_questions", []) if str(item).strip()],
        "missing_decisions": [str(item).strip() for item in goal_spec.get("missing_decisions", []) if str(item).strip()],
        "discussion": goal_spec["discussion"],
        "conversation_language": discussion["conversation_language"],
        "last_explicit_language": discussion["last_explicit_language"],
        "user_confirmation": bool(goal_spec.get("user_confirmation", False)),
        "scorecard": scorecard,
        "stories": stories,
        "stage": stage,
        "status": status,
        "message": message,
        "current_story": None,
        "next_action": next_action,
        "progress": {
            "completed": sum(1 for story in stories if story["status"] == "passed"),
            "total": len(stories),
        },
    }


def load_config(repo_path: Path) -> dict[str, Any]:
    payload = read_json(config_path(repo_path))
    if not isinstance(payload, dict):
        raise RalphRuntimeError("config.json must be an object")
    return payload


def load_state(repo_path: Path) -> dict[str, Any]:
    payload = read_json(state_path(repo_path))
    if not isinstance(payload, dict):
        raise RalphRuntimeError("state.json must be an object")
    stories = payload.get("stories")
    if not isinstance(stories, list) or not stories:
        raise RalphRuntimeError("state.json must contain non-empty stories")
    validate_story_graph(stories)
    return payload


def save_state(repo_path: Path, state: dict[str, Any]) -> None:
    state["progress"] = {
        "completed": sum(1 for story in state["stories"] if story["status"] == "passed"),
        "total": len(state["stories"]),
    }
    write_json(state_path(repo_path), state)


def load_plan_score_summary(repo_path: Path) -> dict[str, Any] | None:
    payload = read_json(plan_score_path(repo_path), required=False)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RalphRuntimeError("plan_score.json must be an object")
    return payload


def next_story(state: dict[str, Any]) -> dict[str, Any] | None:
    story_map = {story["id"]: story for story in state["stories"]}
    for story in state["stories"]:
        if story["status"] == "passed":
            continue
        if story["status"] == "running":
            continue
        if all(story_map[dependency]["status"] == "passed" for dependency in story["dependencies"]):
            return story
    return None


def current_story_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    current = state.get("current_story")
    if current:
        return current
    return next_story(state)


def determine_next_action(state: dict[str, Any]) -> str:
    stage = str(state.get("stage", ""))
    status = str(state.get("status", ""))
    if stage == "discussion":
        discussion = state.get("discussion", {})
        if isinstance(discussion, dict) and discussion.get("current_question"):
            return "answer_current_question"
        return "continue_discussion"
    if stage == "plan_gate":
        return "review_scorecard"
    if stage == "approval_pending":
        return "confirm_run"
    if stage == "task_graph_pending":
        return "approve_task_graph"
    if stage in {"batch_pending", "merge_pending"}:
        return "launch_worker" if stage == "batch_pending" else "merge_task"
    if stage == "worker_done":
        return "collect_worker"
    if stage == "review_required":
        return "review_worker"
    if stage == "rework_pending":
        return "launch_rework"
    if stage == "final_review":
        return "final_review"
    if stage == "handoff_decision":
        return "choose_handoff"
    if stage in {"run", "worker", "tests", "review", "init", "worker_running"} and status == "running":
        return "wait_for_worker"
    if stage == "failed" or status == "failed":
        return "inspect_failure"
    return "wait_for_worker"


def build_ui_prompt(status_payload: dict[str, Any]) -> dict[str, Any] | None:
    if status_payload.get("stage") != "discussion":
        return None
    discussion = status_payload.get("discussion") or {}
    question = discussion.get("current_question")
    if not isinstance(question, dict):
        return None
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        question.get("prompt"),
    )
    localized = localize_question(question, language) or question
    copy = copy_for(language)
    option_ids = [str(option.get("id", "")).strip() for option in localized.get("options", []) if str(option.get("id", "")).strip()]
    title_key = "native_prompt_title_zh" if language == "zh" and "native_prompt_title_zh" in copy else "native_prompt_title"
    return {
        "type": "single_choice",
        "language": language,
        "title": copy[title_key].format(round=str(question.get("id", "Q1")).lstrip("Q") or "1"),
        "summary": discussion.get("summary", ""),
        "question": localized.get("prompt", ""),
        "options": [
            {
                "id": option.get("id"),
                "label": option.get("title", option.get("id")),
                "proposal": option.get("proposal", ""),
                "if_chosen": option.get("if_chosen", ""),
                "tradeoff": option.get("tradeoff", ""),
                "value": option.get("value"),
            }
            for option in localized.get("options", [])
            if isinstance(option, dict)
        ],
        "reply_hint": copy["native_reply_hint_zh"].format(choices=" | ".join(option_ids))
        if language == "zh"
        else copy["native_reply_hint"].format(choices=" | ".join(option_ids)),
    }


def build_status_payload(repo_path: Path) -> dict[str, Any]:
    state = load_state(repo_path)
    events = load_events(repo_path)
    last_event = events[-1] if events else None
    scorecard = load_plan_score_summary(repo_path)
    task_graph = load_task_graph(repo_path, required=False)
    integration = read_json(integration_path(repo_path), required=False)
    conversation_language = pick_language(
        state.get("conversation_language"),
        state.get("last_explicit_language"),
        state.get("goal"),
    )
    current_question = state.get("discussion", {}).get("current_question") if isinstance(state.get("discussion"), dict) else None
    localized_question = localize_question(current_question, conversation_language)
    payload = {
        "project_name": state.get("project_name", ""),
        "branch_name": state.get("branch_name", ""),
        "goal": state.get("goal", ""),
        "allowed_scope": state.get("allowed_scope", []),
        "forbidden_scope": state.get("forbidden_scope", []),
        "verification": state.get("verification", []),
        "risks": state.get("risks", []),
        "stage": state.get("stage", last_event.get("stage") if last_event else "unknown"),
        "status": state.get("status", last_event.get("status") if last_event else "unknown"),
        "message": state.get("message", last_event.get("message") if last_event else ""),
        "discussion": {
            "ready": bool(state.get("discussion_ready", False)),
            "summary": state.get("discussion_summary", ""),
            "open_questions": state.get("open_questions", []),
            "missing_decisions": state.get("missing_decisions", []),
            "current_question": current_question,
            "localized_current_question": localized_question,
            "history": state.get("discussion", {}).get("history", []) if isinstance(state.get("discussion"), dict) else [],
            "task_archetype": state.get("discussion", {}).get("task_archetype") if isinstance(state.get("discussion"), dict) else None,
        },
        "conversation_language": conversation_language,
        "last_explicit_language": pick_language(state.get("last_explicit_language"), conversation_language),
        "scorecard": scorecard,
        "task_graph": task_graph,
        "current_batch": state.get("current_batch"),
        "active_workers": state.get("active_workers", []),
        "review_queue": review_queue_from_task_graph(task_graph),
        "rework_summary": state.get("rework_summary", {}),
        "handoff_options": state.get("handoff_options", []),
        "integration": integration if isinstance(integration, dict) else None,
        "current_story": current_story_payload(state),
        "progress": state.get("progress", {"completed": 0, "total": len(state["stories"])}),
        "plan_score": scorecard,
        "last_event": last_event,
        "events_path": str(events_path(repo_path)),
        "next_action": state.get("next_action") or determine_next_action(state),
    }
    if conversation_language == "zh":
        if payload["stage"] == "discussion" and payload["status"] == "blocked":
            payload["message"] = "讨论尚未完成，当前不能执行。"
        elif payload["stage"] == "plan_gate" and payload["status"] == "blocked":
            payload["message"] = "计划就绪评分卡未通过。"
        elif payload["stage"] == "approval_pending":
            payload["message"] = "运行前仍需最终确认。"
    payload["ui_prompt"] = build_ui_prompt(payload)
    if payload["next_action"] not in DISCUSSION_NEXT_ACTIONS:
        payload["next_action"] = determine_next_action(state)
    return payload


def build_state_summary(state: dict[str, Any]) -> str:
    if str(state.get("stage")) == "discussion":
        language = pick_language(
            state.get("conversation_language"),
            state.get("last_explicit_language"),
            state.get("goal"),
        )
        copy = copy_for(language)
        question = state.get("discussion", {}).get("current_question") if isinstance(state.get("discussion"), dict) else None
        prompt = ""
        if isinstance(question, dict):
            prompt = str((localize_question(question, language) or question).get("prompt", "")).strip()
        if prompt:
            return f"{copy['stage'] if 'stage' in copy else 'Stage'}={state.get('stage')} next_question={prompt}"
        return f"{copy['stage'] if 'stage' in copy else 'Stage'}={state.get('stage')}"
    progress = state.get("progress", {})
    completed = progress.get("completed", 0)
    total = progress.get("total", len(state["stories"]))
    story = current_story_payload(state)
    if story:
        return f"{completed}/{total} complete, next={story['id']}"
    return f"{completed}/{total} complete"


def refresh_repo_state(
    repo_path: Path,
    *,
    preserve_current_story: bool = True,
    current_story: dict[str, Any] | None = None,
    stories: list[dict[str, Any]] | None = None,
    use_existing_raw_score: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    goal_spec = read_json(goal_spec_path(repo_path))
    raw_score = read_json(plan_score_path(repo_path), required=False) if use_existing_raw_score else None
    canonical_goal_spec = canonicalize_goal_spec(goal_spec, raw_score if isinstance(raw_score, dict) else None)
    scorecard = canonical_goal_spec["plan_score"]
    write_json(goal_spec_path(repo_path), canonical_goal_spec)
    write_json(plan_score_path(repo_path), scorecard)
    state = build_state_payload(canonical_goal_spec, scorecard)
    if preserve_current_story and current_story is not None:
        state["current_story"] = current_story
    if preserve_current_story and stories is not None:
        state["stories"] = stories
    save_state(repo_path, state)
    return canonical_goal_spec, scorecard, state


def run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RalphRuntimeError(f"Timed out after {timeout_seconds}s: {' '.join(args)}") from exc
    except OSError as exc:
        raise RalphRuntimeError(f"Failed to launch command: {' '.join(args)}") from exc
    return CommandResult(
        args=args,
        cwd=str(cwd),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = stripped[start : index + 1]
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def normalize_worker_output(parsed: dict[str, Any] | None, raw_result: CommandResult) -> tuple[dict[str, Any], str]:
    if parsed is None:
        return (
            {
                "structured_output": {
                    "status": "failed",
                    "summary": "Claude returned non-JSON output.",
                    "changed_files": [],
                    "tests_run": [],
                    "blockers": ["invalid_json"],
                },
                "returncode": raw_result.returncode,
            },
            "failed",
        )

    structured = parsed.get("structured_output", parsed)
    if not isinstance(structured, dict):
        return (
            {
                "structured_output": {
                    "status": "failed",
                    "summary": "Claude returned JSON with unsupported shape.",
                    "changed_files": [],
                    "tests_run": [],
                    "blockers": ["invalid_shape"],
                },
                "returncode": raw_result.returncode,
            },
            "failed",
        )

    raw_status = str(structured.get("status", "")).lower()
    if raw_status in {"complete", "completed", "pass", "passed"}:
        raw_status = "success"
    if raw_status not in {"success", "blocked", "failed"}:
        raw_status = "success" if raw_result.returncode == 0 else "failed"

    normalized = {
        "structured_output": {
            "status": raw_status,
            "summary": str(structured.get("summary", "")).strip(),
            "changed_files": structured.get("changed_files", []) if isinstance(structured.get("changed_files", []), list) else [],
            "tests_run": structured.get("tests_run", []) if isinstance(structured.get("tests_run", []), list) else [],
            "blockers": structured.get("blockers", []) if isinstance(structured.get("blockers", []), list) else [],
        },
        "returncode": raw_result.returncode,
    }
    if raw_status == "success" and raw_result.returncode == 0:
        return normalized, "passed"
    if raw_status == "blocked":
        return normalized, "blocked"
    return normalized, "failed"


def build_worker_prompt(state: dict[str, Any], story: dict[str, Any]) -> str:
    scope = "\n".join(f"- {item}" for item in state["allowed_scope"])
    forbidden = "\n".join(f"- {item}" for item in state["forbidden_scope"])
    criteria = "\n".join(f"- {item}" for item in story["acceptance_criteria"])
    tests = "\n".join(f"- {item}" for item in story["suggested_tests"])
    risks = "\n".join(f"- {item['risk']}: {item['mitigation']}" for item in state["risks"])
    evidence = "\n".join(f"- {item['file']}:{item['lines']} {item['claim']}" for item in state["codebase_evidence"])
    return textwrap.dedent(
        f"""\
        You are Claude Code running as the only worker inside codex-claude-ralph.

        Rules:
        - Work on exactly one story.
        - Do not re-plan the project.
        - Stay within allowed scope.
        - Do not edit forbidden scope.
        - If blocked, return blocked instead of pretending success.
        - Return JSON only.

        Goal:
        {state['goal']}

        Allowed scope:
        {scope}

        Forbidden scope:
        {forbidden}

        Codebase evidence:
        {evidence}

        Risks:
        {risks}

        Story ID: {story['id']}
        Story Title: {story['title']}
        Story Description: {story['description']}

        Acceptance criteria:
        {criteria}

        Verification commands:
        {tests}

        Required JSON shape:
        {{
          "structured_output": {{
            "status": "success | blocked | failed",
            "summary": "short summary",
            "changed_files": ["path"],
            "tests_run": ["command"],
            "blockers": ["reason"]
          }}
        }}
        """
    ).strip() + "\n"


def build_task_worker_prompt(state: dict[str, Any], task: dict[str, Any], rework_brief: str = "") -> str:
    allowed = task.get("allowed_scope") or state.get("allowed_scope", [])
    forbidden = task.get("forbidden_scope") or state.get("forbidden_scope", [])
    verification = task.get("verification") or []
    criteria = task.get("acceptance_criteria") or []
    return textwrap.dedent(
        f"""\
        You are Claude Code running as a visible terminal worker for codex-claude-ralph v10.

        Role:
        - Implement exactly one task.
        - Do not plan the whole project.
        - Do not communicate with the user.
        - Stay inside this worktree and the allowed scope.
        - Return JSON only when finished.

        Project goal:
        {state.get('goal', '')}

        Task ID:
        {task['task_id']}

        Task title:
        {task['title']}

        Task description:
        {task['description']}

        Acceptance criteria:
        {chr(10).join(f"- {item}" for item in criteria)}

        Allowed scope:
        {chr(10).join(f"- {item}" for item in allowed)}

        Forbidden scope:
        {chr(10).join(f"- {item}" for item in forbidden)}

        Verification:
        {chr(10).join(f"- {item}" for item in verification)}

        Rework brief:
        {rework_brief.strip() or "none"}

        Required JSON shape:
        {{
          "status": "success | blocked | failed",
          "summary": "short summary",
          "changed_files": ["path"],
          "tests_run": ["command"],
          "blockers": ["reason"],
          "notes_for_reviewer": ["detail"]
        }}
        """
    ).strip() + "\n"


def terminal_script_for_command(command: list[str], log_file: Path) -> str:
    quoted_command = " ".join(shlex.quote(part) for part in command)
    quoted_log = shlex.quote(str(log_file))
    return f"{quoted_command} 2>&1 | tee {quoted_log}; echo; echo '[codex-claude-ralph] worker exited with status' $?"


def terminal_open_command(script: str) -> list[str]:
    return ["osascript", "-e", f'tell application "Terminal" to do script {json.dumps(script)}']


def branch_name_for_task(run_id: str, task_id: str) -> str:
    safe_task = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-") or "task"
    return f"codex-ralph/{run_id}/{safe_task}"


def create_task_worktree(repo_path: Path, run_id: str, task: dict[str, Any], *, allow_non_git: bool) -> tuple[Path, str, str]:
    task_id = task["task_id"]
    worktree = task_worktree_path(repo_path, run_id, task_id)
    branch = branch_name_for_task(run_id, task_id)
    if repo_is_git(repo_path):
        if worktree.exists():
            return worktree, branch, "existing_git_worktree"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "-B", branch, str(worktree), "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RalphRuntimeError(f"Failed to create git worktree for `{task_id}`: {stderr}")
        return worktree, branch, "git_worktree"
    if not allow_non_git:
        raise RalphRuntimeError("v10 parallel execution requires a git repo. Use non-git mode only for experimental serial fallback.")
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree, branch, "non_git_experimental"


def run_git_diff(repo_path: Path) -> str:
    result = subprocess.run(["git", "diff", "--binary"], cwd=str(repo_path), capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def commit_task_worktree_changes(worktree: Path, task_id: str) -> dict[str, Any]:
    if not repo_is_git(worktree):
        return {"committed": False, "reason": "not_git"}
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(worktree), capture_output=True, text=True, check=False)
    if status.returncode != 0:
        return {"committed": False, "reason": status.stderr.strip() or status.stdout.strip()}
    if not status.stdout.strip():
        return {"committed": False, "reason": "no_changes"}
    add = subprocess.run(["git", "add", "-A"], cwd=str(worktree), capture_output=True, text=True, check=False)
    if add.returncode != 0:
        raise RalphRuntimeError(f"Failed to stage task `{task_id}` changes: {add.stderr.strip() or add.stdout.strip()}")
    commit = subprocess.run(
        [
            "git",
            "-c",
            "user.name=codex-claude-ralph",
            "-c",
            "user.email=codex-claude-ralph@example.invalid",
            "commit",
            "-m",
            f"codex-ralph: {task_id}",
        ],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        raise RalphRuntimeError(f"Failed to commit task `{task_id}` changes: {commit.stderr.strip() or commit.stdout.strip()}")
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), capture_output=True, text=True, check=False)
    return {"committed": True, "commit": rev.stdout.strip() if rev.returncode == 0 else ""}


def normalize_review_payload(payload: dict[str, Any], verdict: str) -> dict[str, Any]:
    if verdict not in {"passed", "rework", "blocked", "failed"}:
        raise RalphRuntimeError("review verdict must be passed, rework, blocked, or failed")
    scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    normalized_scores = {key: int(scores.get(key, 100 if verdict == "passed" else 0)) for key in REVIEW_SCORE_KEYS}
    return {
        "verdict": verdict,
        "scores": normalized_scores,
        "blocking_issues": payload.get("blocking_issues", []) if isinstance(payload.get("blocking_issues", []), list) else [],
        "rework_instructions": payload.get("rework_instructions", []) if isinstance(payload.get("rework_instructions", []), list) else [],
        "approved_changed_files": payload.get("approved_changed_files", []) if isinstance(payload.get("approved_changed_files", []), list) else [],
        "summary": str(payload.get("summary", "")).strip(),
    }


def maybe_switch_branch(repo_path: Path, state: dict[str, Any], config: dict[str, Any]) -> None:
    if not config.get("require_git", True):
        return
    branch_name = state.get("branch_name")
    if not branch_name:
        return
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if current.returncode == 0 and current.stdout.strip() == branch_name:
        return
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    args = ["git", "switch", branch_name] if exists.returncode == 0 else ["git", "switch", "-c", branch_name]
    result = subprocess.run(args, cwd=str(repo_path), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RalphRuntimeError(f"Failed to switch target branch `{branch_name}`: {stderr}")


def evaluate_plan_gate(score_payload: dict[str, Any] | None, goal_spec: dict[str, Any] | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(goal_spec, dict):
        reasons.append("Missing goal_spec.json")
        return False, reasons
    if not bool(goal_spec.get("discussion_ready", False)):
        reasons.append("GoalSpec discussion_ready is false")
    open_questions = goal_spec.get("open_questions", [])
    if not isinstance(open_questions, list):
        reasons.append("goal_spec.open_questions must be an array")
    elif open_questions:
        reasons.append("Open questions remain: " + "; ".join(str(item) for item in open_questions))
    missing_decisions = goal_spec.get("missing_decisions", [])
    if not isinstance(missing_decisions, list):
        reasons.append("goal_spec.missing_decisions must be an array")
    elif missing_decisions:
        reasons.append("Missing decisions remain: " + "; ".join(str(item) for item in missing_decisions))

    if score_payload is None:
        reasons.append("Missing required plan_score.json")
    else:
        validate_payload_against_schema(score_payload, SCHEMAS_DIR / "plan_score.schema.json")
        total = score_payload.get("total")
        decision = str(score_payload.get("decision", "")).lower()
        hard_blockers = score_payload.get("hard_blockers", [])
        effective_threshold = int(score_payload.get("threshold", PLAN_THRESHOLD))
        if not bool(score_payload.get("discussion_ready", False)):
            reasons.append("plan_score marks discussion as not ready")
        gates = score_payload.get("gates", {})
        for gate_name, gate_threshold in GATE_THRESHOLDS.items():
            gate = gates.get(gate_name, {})
            if not isinstance(gate, dict):
                reasons.append(f"{gate_name} gate is missing")
                continue
            if not bool(gate.get("passed", False)):
                reasons.append(f"{gate_name} gate is blocked")
            if int(gate.get("score", 0)) < int(gate.get("threshold", gate_threshold)):
                reasons.append(f"{gate_name} score is below threshold")
        if not isinstance(total, int):
            reasons.append("plan_score.total must be an integer")
        elif total < effective_threshold:
            reasons.append(f"Plan score {total} is below threshold {effective_threshold}")
        if decision not in {"approved", "pass", "passed"}:
            reasons.append(f"Plan decision is not approved: {decision or 'missing'}")
        if not isinstance(hard_blockers, list):
            reasons.append("plan_score.hard_blockers must be an array")
        elif hard_blockers:
            reasons.append("Hard blockers exist: " + "; ".join(str(item) for item in hard_blockers))
    if not bool(goal_spec.get("user_confirmation", False)):
        reasons.append("GoalSpec user_confirmation is missing or false")
    return not reasons, reasons


def enforce_plan_gate(repo_path: Path) -> tuple[bool, list[str]]:
    score_payload = read_json(plan_score_path(repo_path), required=False)
    goal_spec = read_json(goal_spec_path(repo_path))
    return evaluate_plan_gate(score_payload, goal_spec)


def render_discussion_question(status_payload: dict[str, Any]) -> str:
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        status_payload.get("goal"),
    )
    copy = copy_for(language)
    discussion = status_payload["discussion"]
    question = discussion.get("localized_current_question") or localize_question(discussion.get("current_question") or {}, language) or {}
    options = question.get("options", [])
    option_lines: list[str] = []
    for index, option in enumerate(options[:3]):
        label = option.get("id") or chr(ord("A") + index)
        option_lines.extend(
            [
                "",
                f"{copy['option']} {label}",
                f"- {copy['proposal']}: {option.get('proposal', '')}",
                f"- {copy['if_chosen']}: {option.get('if_chosen', '')}",
                f"- {copy['tradeoff']}: {option.get('tradeoff', '')}",
            ]
        )
    return "\n".join(
        [
            f"{copy['discussion_round']} {question.get('id', 'Q1').lstrip('Q') or '1'}",
            "",
            copy["current_understanding"],
            f"- {copy['goal']}: {localize_goal_text(status_payload.get('goal', ''), language)}",
            f"- {copy['current_best_interpretation']}: {localize_discussion_summary(discussion.get('summary', ''), language)}",
            f"- {copy['why_blocked']}: {', '.join(localize_label_list(discussion.get('missing_decisions', []), language) or [copy['discussion_blocked']])}",
            "",
            copy["question"],
            f"- {question.get('prompt', '')}",
            *option_lines,
            "",
            copy["reply_format"],
            f"- {copy['choose']}: A | B",
            f"- {copy['optional_note']}: ...",
        ]
    ).strip() + "\n"


def render_scorecard(status_payload: dict[str, Any]) -> str:
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        status_payload.get("goal"),
    )
    copy = copy_for(language)
    scorecard = status_payload.get("scorecard") or status_payload.get("plan_score") or {}
    gates = scorecard.get("gates", {})

    def gate_block(name: str, title: str) -> list[str]:
        gate = gates.get(name, {})
        dims = gate.get("dimensions", {})
        lines = [
            title,
            f"- {copy['status']}: {copy['pass'] if gate.get('passed') else copy['blocked']}",
            f"- {copy['score']}: {gate.get('score', 0)}/100",
            f"- {copy['dimensions']}:",
        ]
        for key, value in dims.items():
            lines.append(f"  - {key}: {value}")
        return lines

    hard_blocker_lines = [f"- {item}" for item in scorecard.get("hard_blockers", [])] or [f"- {copy['none']}"]
    open_question_lines = [f"- {item}" for item in status_payload.get("discussion", {}).get("open_questions", [])] or [f"- {copy['none']}"]
    missing_decision_lines = [f"- {localized_decision_label(item, language) if item in DECISION_LABELS else item}" for item in status_payload.get("discussion", {}).get("missing_decisions", [])] or [f"- {copy['none']}"]

    return "\n".join(
        [
            copy["scorecard_title"],
            "",
            copy["overall"],
            f"- {copy['score']}: {scorecard.get('total', 0)}/100",
            f"- {copy['decision']}: {scorecard.get('decision', 'blocked')}",
            f"- {copy['threshold']}: {scorecard.get('threshold', PLAN_THRESHOLD)}",
            "",
            *gate_block("epistemic", copy["gate_epistemic"]),
            "",
            *gate_block("deontic", copy["gate_deontic"]),
            "",
            *gate_block("dialectical", copy["gate_dialectical"]),
            "",
            copy["hard_blockers"],
            *hard_blocker_lines,
            "",
            copy["open_questions"],
            *open_question_lines,
            "",
            copy["missing_decisions"],
            *missing_decision_lines,
            "",
            copy["next_action"],
            f"- {status_payload.get('next_action', 'continue_discussion')}",
        ]
    ).strip() + "\n"


def render_approval_request(status_payload: dict[str, Any]) -> str:
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        status_payload.get("goal"),
    )
    copy = copy_for(language)
    scorecard = status_payload.get("scorecard") or {}
    gates = scorecard.get("gates", {})
    return "\n".join(
        [
            copy["execution_approval"],
            "",
            copy["ready_to_run"],
            f"- {copy['goal']}: {status_payload.get('goal', '') or status_payload.get('message', '')}",
            f"- {copy['scope']}: allowed={', '.join(status_payload.get('allowed_scope', []))}",
            f"- {copy['verification']}: {', '.join(status_payload.get('verification', []))}",
            f"- {copy['risks']}: {', '.join(item['risk'] for item in status_payload.get('risks', []))}",
            "",
            copy["scorecard_title"],
            f"- {copy['overall']}: {scorecard.get('total', 0)}/100",
            f"- {copy['gate_epistemic']}: {gates.get('epistemic', {}).get('score', 0)}/100",
            f"- {copy['gate_deontic']}: {gates.get('deontic', {}).get('score', 0)}/100",
            f"- {copy['gate_dialectical']}: {gates.get('dialectical', {}).get('score', 0)}/100",
            "",
            copy["confirmation_required"],
            f"- {copy['confirm_run']}",
        ]
    ).strip() + "\n"


def render_stage_status(status_payload: dict[str, Any]) -> str:
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        status_payload.get("goal"),
    )
    copy = copy_for(language)
    current_story = status_payload.get("current_story")
    story_text = current_story["id"] + " " + current_story.get("title", "") if isinstance(current_story, dict) else copy["none"]
    return "\n".join(
        [
            copy["stage_update"],
            "",
            copy["stage"],
            f"- {STAGE_LABELS_ZH.get(status_payload.get('stage', ''), status_payload.get('stage', 'unknown')) if language == 'zh' else status_payload.get('stage', 'unknown')}",
            "",
            copy["status"],
            f"- {status_payload.get('status', 'unknown')}",
            "",
            copy["current_story"],
            f"- {story_text.strip()}",
            "",
            copy["next"],
            f"- {status_payload.get('next_action', 'wait_for_worker')}",
        ]
    ).strip() + "\n"


def render_failure_status(status_payload: dict[str, Any]) -> str:
    language = pick_language(
        status_payload.get("conversation_language"),
        status_payload.get("last_explicit_language"),
        status_payload.get("goal"),
    )
    copy = copy_for(language)
    last_event = status_payload.get("last_event") or {}
    return "\n".join(
        [
            copy["stage_failed"],
            "",
            copy["stage"],
            f"- {status_payload.get('stage', 'failed')}",
            "",
            copy["reason"],
            f"- {status_payload.get('message', '')}",
            "",
            copy["evidence"],
            f"- {last_event.get('artifact', status_payload.get('events_path', ''))}",
            "",
            copy["suggested_next_step"],
            f"- {'continue_discussion' if status_payload.get('stage') == 'discussion' else ('inspect_failure' if status_payload.get('status') == 'failed' else 'retry_story')}",
        ]
    ).strip() + "\n"


def render_status_template(status_payload: dict[str, Any]) -> str:
    stage = status_payload.get("stage")
    if stage == "discussion":
        return render_discussion_question(status_payload)
    if stage == "approval_pending":
        return render_approval_request(status_payload)
    if stage == "plan_gate":
        return render_scorecard(status_payload)
    if stage == "failed" or status_payload.get("status") == "failed":
        return render_failure_status(status_payload)
    return render_stage_status(status_payload)


def test_commands_for_story(state: dict[str, Any], story: dict[str, Any]) -> list[str]:
    commands = [str(item).strip() for item in story.get("suggested_tests", []) if str(item).strip()]
    if commands:
        return commands
    return [str(item).strip() for item in state.get("verification", []) if str(item).strip()]


def is_manual_verification_instruction(command: str) -> bool:
    normalized = command.strip()
    if not normalized:
        return True

    explicit_prefixes = (
        "manual verification",
        "manual check",
        "open ",
        "confirm ",
        "play ",
        "inspect ",
        "verify ",
        "launch ",
    )
    lower = normalized.lower()
    if lower.startswith(explicit_prefixes):
        return True

    shell_markers = (
        "|",
        "&&",
        "||",
        ";",
        "$(",
        "`",
        "./",
        "/",
        "python",
        "node",
        "npm",
        "pnpm",
        "yarn",
        "bash",
        "sh ",
        "zsh",
        "git",
        "rg",
        "ls",
        "cat",
        "echo",
        "cd ",
        "make",
        "pytest",
        "uv ",
        "npx",
        "deno",
        "bun",
    )
    if any(marker in lower for marker in shell_markers):
        return False

    first_token = normalized.split()[0]
    if re.fullmatch(r"[A-Za-z0-9._:-]+", first_token):
        return False

    return True


def run_tests(repo_path: Path, state: dict[str, Any], story: dict[str, Any], timeout_seconds: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in test_commands_for_story(state, story):
        if is_manual_verification_instruction(command):
            results.append(
                {
                    "kind": "manual",
                    "command": command,
                    "returncode": None,
                    "status": "manual",
                    "stdout": "",
                    "stderr": "",
                }
            )
            continue
        completed = subprocess.run(
            ["zsh", "-lc", command],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        results.append(
            {
                "kind": "command",
                "command": command,
                "returncode": completed.returncode,
                "status": "passed" if completed.returncode == 0 else "failed",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    return results


def tests_passed(results: list[dict[str, Any]]) -> bool:
    executable_results = [result for result in results if result.get("kind") != "manual"]
    if not executable_results:
        return True
    return all(result.get("status") == "passed" for result in executable_results)


def deterministic_review(
    worker_output: dict[str, Any],
    test_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    worker_status = worker_output["structured_output"]["status"]
    summary = worker_output["structured_output"].get("summary") or ""
    if worker_status == "blocked":
        reason = summary or "Worker reported blocked."
        return (
            {
                "complete": False,
                "reason": reason,
                "remaining_work": worker_output["structured_output"].get("blockers", []) or ["resolve worker blocker"],
            },
            "blocked",
        )
    if worker_status == "failed":
        reason = summary or "Worker failed."
        return (
            {
                "complete": False,
                "reason": reason,
                "remaining_work": worker_output["structured_output"].get("blockers", []) or ["inspect worker failure"],
            },
            "failed",
        )
    if not tests_passed(test_results):
        failed = [
            result["command"]
            for result in test_results
            if result.get("kind") != "manual" and result.get("status") != "passed"
        ]
        return (
            {
                "complete": False,
                "reason": "Verification commands failed.",
                "remaining_work": failed or ["rerun verification"],
            },
            "blocked",
        )
    return (
        {
            "complete": True,
            "reason": summary or "Worker output and verification passed.",
            "remaining_work": [],
        },
        "passed",
    )


def init_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    ensure_writable_repo(repo_path)
    if not args.allow_non_git and not repo_is_git(repo_path):
        raise RalphRuntimeError("Target repo is not a git repository. Re-run init with --allow-non-git only for experimental mode.")

    source_goal_spec = Path(args.goal_spec).expanduser().resolve()
    raw_goal_spec = read_json(source_goal_spec)
    if not isinstance(raw_goal_spec, dict):
        raise RalphRuntimeError("GoalSpec must be a JSON object")

    source_plan_score = Path(args.plan_score).expanduser().resolve() if args.plan_score else None
    raw_score_payload: dict[str, Any] | None = None
    if source_plan_score and source_plan_score.exists():
        payload = read_json(source_plan_score)
        if not isinstance(payload, dict):
            raise RalphRuntimeError("Plan score must be a JSON object")
        raw_score_payload = payload
    elif isinstance(raw_goal_spec.get("plan_score"), dict):
        raw_score_payload = dict(raw_goal_spec["plan_score"])

    ensure_repo_state_dir(repo_path)
    write_json(goal_spec_path(repo_path), raw_goal_spec)
    canonical_goal_spec, score_payload, state = refresh_repo_state(repo_path, preserve_current_story=False)
    validate_payload_against_schema(canonical_goal_spec, SCHEMAS_DIR / "goal_spec.schema.json")
    validate_payload_against_schema(score_payload, SCHEMAS_DIR / "plan_score.schema.json")

    config = build_config_payload(
        repo_path,
        allow_non_git=args.allow_non_git,
        claude_model=args.claude_model,
        timeout_seconds=args.timeout,
    )
    write_json(config_path(repo_path), config)
    append_event(repo_path, stage=state["stage"], status=state["status"], message=state["message"])
    print(f"Initialized Ralph runtime for {repo_path}. {build_state_summary(state)}")


def status_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    payload = build_status_payload(repo_path)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(render_status_template(payload), end="")


def answer_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    ensure_writable_repo(repo_path)
    state = load_state(repo_path)
    if state.get("stage") != "discussion":
        raise RalphRuntimeError("Discussion answers are only valid while the workflow is in discussion stage.")

    goal_spec = read_json(goal_spec_path(repo_path))
    discussion = build_discussion_state(goal_spec)
    question = discussion.get("current_question")
    if not isinstance(question, dict):
        raise RalphRuntimeError("There is no active discussion question to answer.")

    choice = str(args.choice).strip().upper()
    options = [option for option in question.get("options", []) if isinstance(option, dict)]
    selected = next((option for option in options if str(option.get("id", "")).strip().upper() == choice), None)
    if selected is None:
        allowed = ", ".join(str(option.get("id", "")).strip() for option in options)
        raise RalphRuntimeError(f"Invalid discussion choice `{choice}`. Expected one of: {allowed}")

    note = str(args.note or "").strip()
    language = pick_language(
        args.language,
        note,
        state.get("last_explicit_language"),
        state.get("conversation_language"),
        goal_spec.get("last_explicit_language"),
        goal_spec.get("conversation_language"),
        state.get("goal"),
    )

    raw_discussion = goal_spec.get("discussion", {})
    if raw_discussion is not None and not isinstance(raw_discussion, dict):
        raise RalphRuntimeError("GoalSpec `discussion` must be an object")
    raw_discussion = dict(raw_discussion or {})
    history = normalized_history(raw_discussion.get("history", []))
    resolved = normalized_resolved_decisions(raw_discussion.get("resolved_decisions", {}))
    decision_key = str(question.get("decision_key", "")).strip()
    if decision_key == "pressure_pass":
        raw_discussion["pressure_pass_completed"] = True
    else:
        resolved[decision_key] = str(selected.get("value", choice)).strip() or choice
    history.append(
        {
            "id": str(question.get("id", f"Q{len(history) + 1}")).strip(),
            "prompt": str(question.get("prompt", "")).strip(),
            "selected_option": choice,
            "user_note": note,
            "resolved_decision_key": decision_key,
            "language": language,
        }
    )
    raw_discussion["history"] = history
    raw_discussion["resolved_decisions"] = resolved
    raw_discussion["round"] = len(history) + 1
    raw_discussion["last_explicit_language"] = language
    goal_spec["discussion"] = raw_discussion
    goal_spec["conversation_language"] = language
    goal_spec["last_explicit_language"] = language
    goal_spec["user_confirmation"] = False
    write_json(goal_spec_path(repo_path), goal_spec)

    _, _, refreshed_state = refresh_repo_state(repo_path, use_existing_raw_score=False)
    append_event(
        repo_path,
        stage=refreshed_state["stage"],
        status=refreshed_state["status"],
        message=f"Recorded answer {choice} for {decision_key}.",
    )
    payload = build_status_payload(repo_path)
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else render_status_template(payload), end="" if not args.json else "\n")


def doctor_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo) if args.repo else None
    checks = {
        "skill_root": str(SKILL_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "runtime_orchestrator": str(RUNTIME_ROOT / "orchestrator.py"),
        "runtime_facade": str(RUNTIME_ROOT / "ralph.sh"),
        "claude_available": shutil.which("claude") is not None,
        "codex_available": shutil.which("codex") is not None,
    }
    missing = []
    for path in (
        RUNTIME_ROOT / "orchestrator.py",
        RUNTIME_ROOT / "ralph.sh",
        RUNTIME_SCRIPTS_DIR / "ralph-skill-run.sh",
        RUNTIME_SCRIPTS_DIR / "ralph-gate.py",
        RUNTIME_SCRIPTS_DIR / "ralph-events.py",
        RUNTIME_SCRIPTS_DIR / "goal-spec-to-prd.py",
        RUNTIME_SCRIPTS_DIR / "claude-worker-proxy.py",
        RUNTIME_SCRIPTS_DIR / "claude-worker-bridge.py",
        SCHEMAS_DIR / "goal_spec.schema.json",
        SCHEMAS_DIR / "plan_score.schema.json",
        SCHEMAS_DIR / "stage_event.schema.json",
    ):
        if not path.exists():
            missing.append(str(path))
    if repo_path is not None:
        ensure_writable_repo(repo_path)
        checks["repo_path"] = str(repo_path)
        checks["repo_is_git"] = repo_is_git(repo_path)
        checks["state_dir"] = str(state_dir(repo_path))
    checks["missing_paths"] = missing
    if args.json:
        print(json.dumps(checks, indent=2, ensure_ascii=False))
    else:
        for key, value in checks.items():
            print(f"{key}: {value}")
    if missing:
        raise SystemExit(1)
    if not checks["claude_available"]:
        raise SystemExit(127)


def plan_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    ensure_writable_repo(repo_path)
    state = load_state(repo_path)
    source = Path(args.task_graph).expanduser().resolve()
    raw_graph = read_json(source)
    if not isinstance(raw_graph, dict):
        raise RalphRuntimeError("Task graph must be a JSON object")
    graph = normalize_task_graph(raw_graph, state)
    save_task_graph(repo_path, graph)
    for batch in graph["batches"]:
        write_json(batches_dir(repo_path, graph["run_id"]) / f"{batch['batch_id']}.json", batch)
    write_json(
        integration_path(repo_path),
        {
            "run_id": graph["run_id"],
            "integration_branch": f"codex-ralph/{graph['run_id']}/integration",
            "merged_tasks": [],
            "pending_tasks": [task["task_id"] for task in graph["tasks"]],
            "final_review": None,
        },
    )
    state["stage"] = "approval_pending" if graph.get("approved") else "task_graph_pending"
    state["status"] = "blocked"
    state["message"] = "Task graph is ready for user approval." if not graph.get("approved") else "Task graph approved. Ready to launch workers."
    state["task_graph_run_id"] = graph["run_id"]
    state["current_batch"] = graph["batches"][0] if graph["batches"] else None
    state["active_workers"] = []
    state["review_queue"] = []
    state["rework_summary"] = {"max_rework_attempts": MAX_REWORK_ATTEMPTS, "blocked_tasks": []}
    state["handoff_options"] = []
    state["next_action"] = "confirm_run" if graph.get("approved") else "approve_task_graph"
    save_state(repo_path, state)
    append_event(repo_path, stage=state["stage"], status=state["status"], message=state["message"], run_id=graph["run_id"], artifact=str(task_graph_path(repo_path)))
    payload = build_status_payload(repo_path)
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else render_stage_status(payload), end="" if not args.json else "\n")


def launch_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    ensure_writable_repo(repo_path)
    config = load_config(repo_path)
    state = load_state(repo_path)
    graph = load_task_graph(repo_path)
    assert graph is not None
    run_id = args.run_id or graph.get("run_id") or utc_stamp()
    task = find_task(graph, args.task_id)
    allow_non_git = not bool(config.get("require_git", True))
    worktree, branch, mode = create_task_worktree(repo_path, run_id, task, allow_non_git=allow_non_git)
    artifact_dir = task_artifact_dir(repo_path, run_id, task["task_id"])
    task_file = artifact_dir / "task.json"
    brief_file = artifact_dir / "brief.md"
    prompt_file = artifact_dir / "claude_prompt.md"
    raw_log = artifact_dir / "worker_raw.log"
    worker_output = artifact_dir / "worker_output.json"
    rework_brief_path = artifact_dir / "rework_brief.md"
    rework_brief = rework_brief_path.read_text(encoding="utf-8") if rework_brief_path.exists() else ""

    write_json(task_file, task)
    prompt = build_task_worker_prompt(state, task, rework_brief)
    write_text(brief_file, prompt)
    write_text(prompt_file, prompt)

    command = [
        sys.executable,
        str(RUNTIME_SCRIPTS_DIR / "claude-worker-bridge.py"),
        "run",
        "--repo",
        str(repo_path),
        "--cwd",
        str(worktree),
        "--story-id",
        task["task_id"],
        "--story-title",
        task["title"],
        "--brief-file",
        str(task_file),
        "--prompt-file",
        str(prompt_file),
        "--output",
        str(worker_output),
        "--raw-output",
        str(artifact_dir / "worker_raw.json"),
        "--timeout",
        str(int(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))),
    ]
    if config.get("claude_model"):
        command.extend(["--model", str(config["claude_model"])])

    terminal_script = terminal_script_for_command(command, raw_log)
    terminal_command = terminal_open_command(terminal_script)
    launched = False
    launch_error = ""
    if args.visible_terminal:
        result = subprocess.run(terminal_command, cwd=str(repo_path), capture_output=True, text=True, check=False)
        launched = result.returncode == 0
        launch_error = result.stderr.strip() or result.stdout.strip()

    task["status"] = "worker_running"
    task["worktree"] = str(worktree)
    task["branch"] = branch
    task["last_run_id"] = run_id
    task["launch_mode"] = mode
    task["terminal_command"] = terminal_command
    task["worker_output"] = str(worker_output)
    save_task_graph(repo_path, graph)

    state["stage"] = "worker_running"
    state["status"] = "running"
    state["message"] = f"Claude worker launched for {task['task_id']}." if launched or not args.visible_terminal else f"Claude worker launch command prepared for {task['task_id']}."
    state["active_workers"] = [
        *(worker for worker in state.get("active_workers", []) if worker.get("task_id") != task["task_id"]),
        {"task_id": task["task_id"], "worktree": str(worktree), "branch": branch, "terminal_visible": bool(args.visible_terminal), "launched": launched},
    ]
    state["next_action"] = "wait_for_worker"
    save_state(repo_path, state)
    append_event(repo_path, stage="worker_running", status="running", message=state["message"], run_id=run_id, story_id=task["task_id"], artifact=str(prompt_file))
    payload = {
        "task_id": task["task_id"],
        "run_id": run_id,
        "worktree": str(worktree),
        "branch": branch,
        "terminal_command": terminal_command,
        "terminal_script": terminal_script,
        "launched": launched,
        "launch_error": launch_error,
        "worker_output": str(worker_output),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def collect_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    state = load_state(repo_path)
    graph = load_task_graph(repo_path)
    assert graph is not None
    task = find_task(graph, args.task_id)
    run_id = args.run_id or task.get("last_run_id") or graph.get("run_id")
    if not run_id:
        raise RalphRuntimeError("collect requires --run-id or a launched task")
    artifact_dir = task_artifact_dir(repo_path, str(run_id), task["task_id"])
    output_file = artifact_dir / "worker_output.json"
    output = read_json(output_file, required=False)
    worktree = Path(str(task.get("worktree") or ""))
    diff_file = artifact_dir / "diff.patch"
    commit_result = {"committed": False, "reason": "missing_worktree"}
    if worktree.exists() and repo_is_git(worktree):
        write_text(diff_file, run_git_diff(worktree))
        commit_result = commit_task_worktree_changes(worktree, task["task_id"])
    task["status"] = "review_required"
    task["worker_output"] = str(output_file)
    task["diff"] = str(diff_file)
    task["commit"] = commit_result.get("commit")
    save_task_graph(repo_path, graph)
    state["stage"] = "review_required"
    state["status"] = "blocked"
    state["message"] = f"Worker output is ready for Codex review: {task['task_id']}."
    state["active_workers"] = [worker for worker in state.get("active_workers", []) if worker.get("task_id") != task["task_id"]]
    state["review_queue"] = review_queue_from_task_graph(graph)
    state["next_action"] = "review_worker"
    save_state(repo_path, state)
    append_event(repo_path, stage="review_required", status="blocked", message=state["message"], run_id=str(run_id), story_id=task["task_id"], artifact=str(output_file))
    print(json.dumps({"task": task, "worker_output": output, "diff_path": str(diff_file), "commit": commit_result, "next_action": "review_worker"}, indent=2, ensure_ascii=False))


def review_mark_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    state = load_state(repo_path)
    graph = load_task_graph(repo_path)
    assert graph is not None
    task = find_task(graph, args.task_id)
    review_source = Path(args.review).expanduser().resolve()
    raw_review = read_json(review_source)
    if not isinstance(raw_review, dict):
        raise RalphRuntimeError("Review payload must be a JSON object")
    review = normalize_review_payload(raw_review, args.verdict)
    run_id = str(args.run_id or task.get("last_run_id") or graph.get("run_id") or utc_stamp())
    artifact_dir = task_artifact_dir(repo_path, run_id, task["task_id"])
    review_path = artifact_dir / "review.json"
    write_json(review_path, review)
    task["review"] = review

    if review["verdict"] == "passed":
        task["status"] = "merge_pending"
        state["stage"] = "merge_pending"
        state["status"] = "blocked"
        state["message"] = f"Task {task['task_id']} passed Codex review and is ready to merge."
        state["next_action"] = "merge_task"
    elif review["verdict"] == "rework":
        task["rework_attempt_count"] = int(task.get("rework_attempt_count", 0)) + 1
        history = task.get("rework_history", [])
        history.append({"attempt": task["rework_attempt_count"], "review": review, "timestamp": utc_now()})
        task["rework_history"] = history
        rework_text = "\n".join(f"- {item}" for item in review["rework_instructions"] or review["blocking_issues"] or ["Address Codex review blockers."])
        write_text(artifact_dir / "rework_brief.md", rework_text + "\n")
        if task["rework_attempt_count"] >= int(task.get("max_rework_attempts", MAX_REWORK_ATTEMPTS)):
            task["status"] = "handoff_decision"
            state["stage"] = "handoff_decision"
            state["status"] = "blocked"
            state["message"] = f"Task {task['task_id']} reached the rework limit."
            state["handoff_options"] = ["continue_claude_rework", "codex_takeover"]
            state["next_action"] = "choose_handoff"
        else:
            task["status"] = "rework_pending"
            state["stage"] = "rework_pending"
            state["status"] = "blocked"
            state["message"] = f"Task {task['task_id']} needs Claude rework attempt {task['rework_attempt_count']}."
            state["next_action"] = "launch_rework"
    else:
        task["status"] = "failed" if review["verdict"] == "failed" else "blocked"
        state["stage"] = "failed"
        state["status"] = task["status"]
        state["message"] = review["summary"] or f"Task {task['task_id']} review verdict: {review['verdict']}."
        state["next_action"] = "inspect_failure"

    state["review_queue"] = review_queue_from_task_graph(graph)
    state["rework_summary"] = {
        "max_rework_attempts": int(task.get("max_rework_attempts", MAX_REWORK_ATTEMPTS)),
        "task_id": task["task_id"],
        "attempts": int(task.get("rework_attempt_count", 0)),
        "last_verdict": review["verdict"],
    }
    save_task_graph(repo_path, graph)
    save_state(repo_path, state)
    append_event(repo_path, stage=state["stage"], status=state["status"], message=state["message"], run_id=run_id, story_id=task["task_id"], artifact=str(review_path))
    print(json.dumps(build_status_payload(repo_path), indent=2, ensure_ascii=False))


def merge_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    state = load_state(repo_path)
    graph = load_task_graph(repo_path)
    assert graph is not None
    task = find_task(graph, args.task_id)
    if task.get("status") != "merge_pending":
        raise RalphRuntimeError(f"Task `{task['task_id']}` is not ready to merge")
    if repo_is_git(repo_path) and task.get("branch"):
        result = subprocess.run(["git", "merge", "--no-ff", "--no-edit", str(task["branch"])], cwd=str(repo_path), capture_output=True, text=True, check=False)
        if result.returncode != 0:
            task["status"] = "rework_pending"
            state["stage"] = "rework_pending"
            state["status"] = "blocked"
            state["message"] = f"Merge conflict for {task['task_id']}: {(result.stderr or result.stdout).strip()}"
            state["next_action"] = "launch_rework"
            save_task_graph(repo_path, graph)
            save_state(repo_path, state)
            append_event(repo_path, stage="rework_pending", status="blocked", message=state["message"], story_id=task["task_id"])
            print(json.dumps(build_status_payload(repo_path), indent=2, ensure_ascii=False))
            return
    task["status"] = "passed"
    integration = read_json(integration_path(repo_path), required=False)
    if not isinstance(integration, dict):
        integration = {"merged_tasks": [], "pending_tasks": []}
    merged = [str(item) for item in integration.get("merged_tasks", [])]
    if task["task_id"] not in merged:
        merged.append(task["task_id"])
    integration["merged_tasks"] = merged
    integration["pending_tasks"] = [item["task_id"] for item in graph["tasks"] if item.get("status") != "passed"]
    write_json(integration_path(repo_path), integration)
    save_task_graph(repo_path, graph)
    if all(item.get("status") == "passed" for item in graph["tasks"]):
        state["stage"] = "final_review"
        state["status"] = "blocked"
        state["message"] = "All tasks merged. Codex final review is required."
        state["next_action"] = "final_review"
    else:
        state["stage"] = "batch_pending"
        state["status"] = "blocked"
        state["message"] = f"Task {task['task_id']} merged. Continue with next ready batch."
        state["next_action"] = "launch_worker"
    save_state(repo_path, state)
    append_event(repo_path, stage=state["stage"], status=state["status"], message=state["message"], story_id=task["task_id"], artifact=str(integration_path(repo_path)))
    print(json.dumps(build_status_payload(repo_path), indent=2, ensure_ascii=False))


def handoff_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    state = load_state(repo_path)
    if state.get("stage") != "handoff_decision":
        raise RalphRuntimeError("handoff is only valid in handoff_decision stage")
    if args.mode not in {"continue_claude_rework", "codex_takeover"}:
        raise RalphRuntimeError("handoff mode must be continue_claude_rework or codex_takeover")
    if args.mode == "continue_claude_rework":
        state["stage"] = "rework_pending"
        state["status"] = "blocked"
        state["message"] = "User approved another Claude rework attempt after the default limit."
        state["next_action"] = "launch_rework"
    else:
        state["stage"] = "handoff_decision"
        state["status"] = "blocked"
        state["message"] = "User selected Codex/GPT takeover in the current conversation."
        state["next_action"] = "codex_takeover"
    state["handoff_mode"] = args.mode
    save_state(repo_path, state)
    append_event(repo_path, stage="handoff_decision", status="blocked", message=state["message"])
    print(json.dumps(build_status_payload(repo_path), indent=2, ensure_ascii=False))


def playwright_command(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    graph = load_task_graph(repo_path, required=False)
    task: dict[str, Any] | None = None
    if graph:
        task = find_task(graph, args.task_id) if args.task_id else None
    spec_name = f"{args.task_id or 'final'}.spec.ts"
    spec_path = playwright_dir(repo_path) / spec_name
    screenshots = playwright_dir(repo_path) / "screenshots"
    traces = playwright_dir(repo_path) / "traces"
    screenshots.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)
    target_url = args.url or "http://127.0.0.1:3000"
    title = (task or {}).get("title", args.task_id or "final review")
    spec = textwrap.dedent(
        f"""\
        import {{ test, expect }} from '@playwright/test';

        test('codex-claude-ralph smoke: {title}', async ({{ page }}) => {{
          const errors: string[] = [];
          page.on('pageerror', error => errors.push(error.message));
          page.on('console', message => {{
            if (message.type() === 'error') errors.push(message.text());
          }});
          await page.goto({json.dumps(target_url)}, {{ waitUntil: 'networkidle' }});
          await expect(page.locator('body')).toBeVisible();
          await page.screenshot({{ path: {json.dumps(str(screenshots / f"{args.task_id or 'final'}-desktop.png"))}, fullPage: true }});
          const canvasCount = await page.locator('canvas').count();
          if (canvasCount > 0) {{
            const nonBlank = await page.locator('canvas').first().evaluate((canvas: HTMLCanvasElement) => {{
              const ctx = canvas.getContext('2d');
              if (!ctx) return true;
              const data = ctx.getImageData(0, 0, Math.min(canvas.width, 64), Math.min(canvas.height, 64)).data;
              return Array.from(data).some(value => value !== 0);
            }});
            expect(nonBlank).toBeTruthy();
          }}
          expect(errors).toEqual([]);
        }});
        """
    )
    write_text(spec_path, spec)
    payload = {
        "status": "generated",
        "task_id": args.task_id,
        "spec_path": str(spec_path),
        "screenshots_dir": str(screenshots),
        "traces_dir": str(traces),
        "recommended_command": f"npx playwright test {shlex.quote(str(spec_path))}",
        "target_url": target_url,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def run_command_loop(args: argparse.Namespace) -> None:
    repo_path = repo_path_from_args(args.repo)
    ensure_writable_repo(repo_path)
    config = load_config(repo_path)
    state = load_state(repo_path)

    if config.get("require_git", True) and not repo_is_git(repo_path):
        raise RalphRuntimeError("Configured target repo requires git, but current repo is not git.")

    approved, reasons = enforce_plan_gate(repo_path)
    if not approved:
        goal_spec, scorecard, state = refresh_repo_state(
            repo_path,
            preserve_current_story=True,
            current_story=state.get("current_story"),
            stories=state.get("stories"),
        )
        discussion = build_discussion_state(goal_spec)
        state["scorecard"] = scorecard
        state["message"] = "Plan gate blocked execution. " + " | ".join(reasons)
        if not discussion["ready"]:
            state["stage"] = "discussion"
            state["next_action"] = "answer_current_question" if discussion.get("current_question") else "continue_discussion"
        elif not bool(goal_spec.get("user_confirmation", False)):
            state["stage"] = "approval_pending"
            state["next_action"] = "confirm_run"
        else:
            state["stage"] = "plan_gate"
            state["next_action"] = "review_scorecard"
        state["status"] = "blocked"
        save_state(repo_path, state)
        append_event(repo_path, stage=state["stage"], status="blocked", message=state["message"])
        print(state["message"])
        return

    maybe_switch_branch(repo_path, state, config)
    timeout_seconds = int(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    visualizer = TerminalRunVisualizer(enabled=bool(args.visual))

    state["stage"] = "run"
    state["status"] = "running"
    state["message"] = "Ralph run started."
    state["next_action"] = "wait_for_worker"
    save_state(repo_path, state)
    append_event(repo_path, stage="run", status="running", message="Ralph run started.")

    steps_taken = 0
    while steps_taken < args.max_steps:
        story = next_story(state)
        if story is None:
            state["stage"] = "complete"
            state["status"] = "passed"
            state["message"] = "All stories are complete."
            state["current_story"] = None
            state["next_action"] = "wait_for_worker"
            save_state(repo_path, state)
            append_event(repo_path, stage="complete", status="passed", message="All stories are complete.")
            break

        steps_taken += 1
        run_id = utc_stamp()
        story["status"] = "running"
        story["attempt_count"] = int(story.get("attempt_count", 0)) + 1
        story["last_run_id"] = run_id
        state["stage"] = "worker"
        state["status"] = "running"
        state["message"] = f"Running worker for {story['id']}."
        state["current_story"] = {"id": story["id"], "title": story["title"], "status": "running"}
        state["next_action"] = "wait_for_worker"
        save_state(repo_path, state)
        visualizer.begin_story(story)

        brief_payload = {
            "story_id": story["id"],
            "title": story["title"],
            "goal": state["goal"],
            "acceptance_criteria": story["acceptance_criteria"],
            "test_commands": test_commands_for_story(state, story),
            "allowed_scope": state["allowed_scope"],
            "forbidden_scope": state["forbidden_scope"],
        }
        brief_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_brief.json"
        prompt_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_prompt.md"
        worker_output_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_worker.json"
        worker_raw_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_worker_raw.json"
        tests_output_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_tests.json"
        review_output_file = runs_dir(repo_path) / f"{run_id}_{story['id']}_review.json"

        write_json(brief_file, brief_payload)
        prompt = build_worker_prompt(state, story)
        write_text(prompt_file, prompt)
        visualizer.stage("worker", f"Invoking Claude for {story['id']}")

        bridge_command = [
            sys.executable,
            str(RUNTIME_SCRIPTS_DIR / "claude-worker-bridge.py"),
            "run",
            "--repo",
            str(repo_path),
            "--cwd",
            str(repo_path),
            "--story-id",
            story["id"],
            "--story-title",
            story["title"],
            "--brief-file",
            str(brief_file),
            "--prompt-file",
            str(prompt_file),
            "--output",
            str(worker_output_file),
            "--raw-output",
            str(worker_raw_file),
            "--timeout",
            str(timeout_seconds),
        ]
        if config.get("claude_model"):
            bridge_command.extend(["--model", str(config["claude_model"])])
        raw_result = run_command(bridge_command, cwd=repo_path, timeout_seconds=timeout_seconds)
        raw_payload = read_json(worker_raw_file, required=False)
        if raw_payload is None:
            write_json(worker_raw_file, raw_result.to_dict())
        worker_output = read_json(worker_output_file, required=False)
        if not isinstance(worker_output, dict):
            parsed = extract_first_json_object(raw_result.stdout)
            worker_output, _ = normalize_worker_output(parsed, raw_result)
            write_json(worker_output_file, worker_output)
        structured_status = str(worker_output.get("structured_output", {}).get("status", "failed")).lower()
        mapped_status = "passed" if structured_status == "success" else ("blocked" if structured_status == "blocked" else "failed")

        if mapped_status != "passed":
            story["status"] = "blocked" if mapped_status == "blocked" else "failed"
            story["remaining_work"] = worker_output["structured_output"].get("blockers", [])
            story["last_review_reason"] = worker_output["structured_output"].get("summary") or "Worker did not pass."
            state["stage"] = "failed"
            state["status"] = story["status"]
            state["message"] = story["last_review_reason"]
            state["current_story"] = {"id": story["id"], "title": story["title"], "status": story["status"]}
            state["next_action"] = "inspect_failure"
            save_state(repo_path, state)
            append_event(repo_path, stage="failed", status=story["status"], message=state["message"], run_id=run_id, story_id=story["id"], artifact=str(worker_output_file))
            break

        visualizer.stage("tests", f"Running verification for {story['id']}")
        test_results = run_tests(repo_path, state, story, timeout_seconds)
        write_json(tests_output_file, test_results)
        test_stage_status = "passed" if tests_passed(test_results) else "blocked"
        append_event(
            repo_path,
            stage="tests",
            status=test_stage_status,
            message="Verification finished." if test_stage_status == "passed" else "Verification failed.",
            run_id=run_id,
            story_id=story["id"],
            artifact=str(tests_output_file),
            next_stage="review",
        )

        visualizer.stage("review", f"Reviewing deterministic evidence for {story['id']}")
        review_payload, review_status = deterministic_review(worker_output, test_results)
        write_json(review_output_file, review_payload)
        append_event(
            repo_path,
            stage="review",
            status="passed" if review_status == "passed" else "blocked",
            message=review_payload["reason"],
            run_id=run_id,
            story_id=story["id"],
            artifact=str(review_output_file),
            next_stage="complete" if review_status == "passed" else "failed",
        )

        if review_status == "passed":
            story["status"] = "passed"
            story["remaining_work"] = []
            story["last_review_reason"] = review_payload["reason"]
            state["stage"] = "run"
            state["status"] = "running"
            state["message"] = f"Story {story['id']} passed."
            state["current_story"] = None
            state["next_action"] = "wait_for_worker"
            save_state(repo_path, state)
            if all(item["status"] == "passed" for item in state["stories"]):
                state["stage"] = "complete"
                state["status"] = "passed"
                state["message"] = "All stories are complete."
                state["next_action"] = "wait_for_worker"
                save_state(repo_path, state)
                append_event(repo_path, stage="complete", status="passed", message="All stories are complete.")
                break
            continue

        story["status"] = "blocked"
        story["remaining_work"] = review_payload["remaining_work"]
        story["last_review_reason"] = review_payload["reason"]
        state["stage"] = "failed"
        state["status"] = "blocked"
        state["message"] = review_payload["reason"]
        state["current_story"] = {"id": story["id"], "title": story["title"], "status": "blocked"}
        state["next_action"] = "inspect_failure"
        save_state(repo_path, state)
        append_event(repo_path, stage="failed", status="blocked", message=review_payload["reason"], run_id=run_id, story_id=story["id"], artifact=str(review_output_file))
        break

    final_state = load_state(repo_path)
    payload = build_status_payload(repo_path)
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else build_state_summary(final_state))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="codex-claude-ralph v10 runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize target repo Ralph state from GoalSpec")
    init_parser.add_argument("--repo", help="Target repository path")
    init_parser.add_argument("--goal-spec", required=True, help="Path to GoalSpec JSON")
    init_parser.add_argument("--plan-score", help="Optional path to Plan Score JSON")
    init_parser.add_argument("--allow-non-git", action="store_true", help="Allow explicit experimental non-git mode")
    init_parser.add_argument("--claude-model", help="Claude model override")
    init_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Worker/test timeout in seconds")
    init_parser.set_defaults(func=init_command)

    run_parser = subparsers.add_parser("run", help="Run the Ralph workflow")
    run_parser.add_argument("--repo", help="Target repository path")
    run_parser.add_argument("--max-steps", type=int, default=5)
    run_parser.add_argument("--visual", action="store_true", help="Render terminal stage updates")
    run_parser.add_argument("--json", action="store_true", help="Print final status payload as JSON")
    run_parser.set_defaults(func=run_command_loop)

    plan_parser = subparsers.add_parser("plan", help="Persist and expose a v10 task graph for user approval")
    plan_parser.add_argument("--repo", help="Target repository path")
    plan_parser.add_argument("--task-graph", required=True, help="Path to task_graph JSON")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.set_defaults(func=plan_command)

    launch_parser = subparsers.add_parser("launch", help="Launch a visible Claude worker for a task")
    launch_parser.add_argument("--repo", help="Target repository path")
    launch_parser.add_argument("--task-id", required=True)
    launch_parser.add_argument("--run-id")
    launch_parser.add_argument("--visible-terminal", action="store_true")
    launch_parser.set_defaults(func=launch_command)

    collect_parser = subparsers.add_parser("collect", help="Collect worker artifacts and mark a task ready for Codex review")
    collect_parser.add_argument("--repo", help="Target repository path")
    collect_parser.add_argument("--task-id", required=True)
    collect_parser.add_argument("--run-id")
    collect_parser.set_defaults(func=collect_command)

    review_parser = subparsers.add_parser("review-mark", help="Persist Codex review verdict for a task")
    review_parser.add_argument("--repo", help="Target repository path")
    review_parser.add_argument("--task-id", required=True)
    review_parser.add_argument("--verdict", required=True, choices=["passed", "rework", "blocked", "failed"])
    review_parser.add_argument("--review", required=True, help="Path to Codex review JSON")
    review_parser.add_argument("--run-id")
    review_parser.set_defaults(func=review_mark_command)

    merge_parser = subparsers.add_parser("merge", help="Merge an approved task worktree branch")
    merge_parser.add_argument("--repo", help="Target repository path")
    merge_parser.add_argument("--task-id", required=True)
    merge_parser.add_argument("--run-id")
    merge_parser.set_defaults(func=merge_command)

    handoff_parser = subparsers.add_parser("handoff", help="Record user choice after rework limit")
    handoff_parser.add_argument("--repo", help="Target repository path")
    handoff_parser.add_argument("--mode", required=True, choices=["continue_claude_rework", "codex_takeover"])
    handoff_parser.set_defaults(func=handoff_command)

    playwright_parser = subparsers.add_parser("playwright", help="Generate a v10 Playwright smoke spec for a UI task")
    playwright_parser.add_argument("--repo", help="Target repository path")
    playwright_parser.add_argument("--task-id")
    playwright_parser.add_argument("--url")
    playwright_parser.set_defaults(func=playwright_command)

    status_parser = subparsers.add_parser("status", help="Show stable status payload")
    status_parser.add_argument("--repo", help="Target repository path")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=status_command)

    answer_parser = subparsers.add_parser("answer", help="Record one discussion answer and advance the workflow state")
    answer_parser.add_argument("--repo", help="Target repository path")
    answer_parser.add_argument("--choice", required=True, help="Selected option id, for example A or B")
    answer_parser.add_argument("--note", help="Optional user note to persist with the answer")
    answer_parser.add_argument("--language", help="Optional language override: zh or en")
    answer_parser.add_argument("--json", action="store_true", help="Print the refreshed status payload as JSON")
    answer_parser.set_defaults(func=answer_command)

    doctor_parser = subparsers.add_parser("doctor", help="Validate runtime installation and target repo access")
    doctor_parser.add_argument("--repo", help="Target repository path")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(func=doctor_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except RalphRuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
