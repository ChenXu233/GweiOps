# src/services/template.py


class TemplateEngine:
    """生成 GitHub Issue 评论模板。"""

    def render_patch_options(self, patches: list[dict]) -> str:
        """渲染修复方案选项。"""
        if not patches:
            return "无可用方案"

        lines = ["## 🛠️ 修复方案\n"]

        for i, patch in enumerate(patches):
            letter = chr(ord("A") + i)
            lines.append(f"### 方案 {letter}：{patch['type']}")
            lines.append(f"- **风险**：{patch['risk']}")
            lines.append(f"- **说明**：{patch['description']}")
            lines.append("")

        return "\n".join(lines)

    def render_analysis_report(self, analysis: dict) -> str:
        """渲染分析报告。"""
        return (
            f"## 📊 Issue 分析报告\n\n"
            f"**类型**：{analysis.get('type', '未知')}\n"
            f"**标题**：{analysis.get('title', '无')}\n\n"
            f"**摘要**：{analysis.get('summary', '无')}\n"
        )

    def render_duplicate_comment(self, original_issue: int, similarity: float) -> str:
        """渲染重复 Issue 评论。"""
        return (
            f"## ⚠️ 疑似重复\n\n"
            f"此 Issue 与 #{original_issue} 相似度为 {similarity:.0%}。\n\n"
            f"如果这是重复 Issue，请关闭此 Issue 并在 #{original_issue} 中讨论。"
        )

    def render_incomplete_comment(self, missing_fields: list[str]) -> str:
        """渲染不完整 Issue 评论。"""
        fields_str = "、".join(missing_fields)
        return (
            f"## ❓ 信息不完整\n\n"
            f"此 Issue 缺少以下必要信息：**{fields_str}**\n\n"
            f"请补充以下内容后重新提交：\n"
            + "\n".join(f"- {field}" for field in missing_fields)
        )

    def render_waiting_comment(self, patches: list[dict]) -> str:
        """渲染等待用户选择的评论。"""
        options = []
        for i, patch in enumerate(patches):
            letter = chr(ord("A") + i)
            options.append(f"- **{letter}**：{patch['type']}（{patch['risk']}风险）")

        return (
            f"## 🛠️ 请选择修复方案\n\n"
            + "\n".join(options)
            + "\n\n请回复选择方案（A/B/C），或提出修改建议。"
        )
