# engine/shared/render.py
"""把结构化结果渲染成面向人的文本。

工作流与 intent 提供者共用同一份渲染,所以它不能住在 engine.workflows 里——
插件不该反过来 import 工作流。
"""

from __future__ import annotations

from typing import Any


def format_suggestion_reply(payload: dict[str, Any], patches: list[dict]) -> str:
    """把补丁建议格式化为 Issue 评论 Markdown(纯函数,保持确定性)。"""
    lines = [
        "## 🛠 GweiOps 修复建议",
        "",
        f"针对 **{payload['title']}** 生成了 {len(patches)} 个候选补丁（仅建议，未自动应用）：",
        "",
    ]
    for i, patch in enumerate(patches, 1):
        lines += [
            f"### 方案 {i} · {patch.get('type', 'PATCH')}（风险：{patch.get('risk', '未知')}）",
            "",
            patch.get("description", ""),
            "",
            "```diff",
            patch.get("diff", ""),
            "```",
            "",
        ]
    lines += ["---", "*由 GweiOps 生成；如需调整请回复 @gwei 并补充说明。*"]
    return "\n".join(lines)
