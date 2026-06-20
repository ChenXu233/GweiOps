# src/services/review_report.py
from src.services.code_reviewer import ReviewResult, ReviewIssue


class ReviewReportGenerator:
    """生成代码审查报告。"""

    def generate(self, result: ReviewResult) -> str:
        """生成纯文本报告。"""
        lines = [
            "## 🔍 代码审查报告",
            "",
            f"**分数**：{result.score}/100",
            f"**摘要**：{result.summary}",
            "",
        ]

        if not result.issues:
            lines.append("✅ 未发现代码质量问题")
        else:
            lines.append("### 发现的问题")
            lines.append("")

            for issue in result.issues:
                severity_icon = self._get_severity_icon(issue.severity)
                location = f"第 {issue.line} 行" if issue.line else "未知位置"
                lines.append(f"- {severity_icon} **{issue.severity.upper()}**：{issue.message} ({location})")

        return "\n".join(lines)

    def generate_markdown(self, result: ReviewResult) -> str:
        """生成 Markdown 格式报告。"""
        lines = [
            "## 🔍 代码审查报告",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 分数 | {result.score}/100 |",
            f"| 问题数 | {len(result.issues)} |",
            "",
        ]

        if not result.issues:
            lines.append("✅ **未发现代码质量问题**")
        else:
            lines.append("### 发现的问题")
            lines.append("")
            lines.append("| 严重性 | 位置 | 问题 |")
            lines.append("|--------|------|------|")

            for issue in result.issues:
                severity_icon = self._get_severity_icon(issue.severity)
                location = f"第 {issue.line} 行" if issue.line else "-"
                lines.append(f"| {severity_icon} {issue.severity} | {location} | {issue.message} |")

        return "\n".join(lines)

    def _get_severity_icon(self, severity: str) -> str:
        """获取严重性图标。"""
        icons = {
            "error": "🔴",
            "warning": "🟡",
            "info": "💡",
        }
        return icons.get(severity, "❓")
