# src/services/labeler.py
from dataclasses import dataclass, field


@dataclass
class LabelMapping:
    keywords: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.keywords:
            self.keywords = {
                "lexer": ["lexer", "token", "scan", "词法"],
                "parser": ["parser", "ast", "syntax", "语法"],
                "type-checker": ["type", "checker", "inference", "类型"],
                "codegen": ["codegen", "ir", "代码生成"],
                "runtime": ["runtime", "panic", "运行时"],
                "cli": ["cli", "command", "命令行"],
                "docs": ["docs", "documentation", "文档", "readme"],
            }

    @classmethod
    def from_config(cls, config: dict) -> "LabelMapping":
        mapping_data = config.get("labels", {}).get("mapping", {})
        return cls(keywords=mapping_data)


class LabelGenerator:
    """根据 Issue 内容生成标签。"""

    def __init__(self, mapping: LabelMapping | None = None):
        self.mapping = mapping or LabelMapping()

    def generate(self, title: str, body: str) -> list[str]:
        """根据标题和内容生成标签列表。"""
        combined = f"{title} {body}".lower()
        labels = []

        # 检查关键词匹配
        for label, keywords in self.mapping.keywords.items():
            if any(kw in combined for kw in keywords):
                labels.append(label)

        # 检查 issue 类型
        bug_keywords = ["crash", "bug", "error", "fail", "broken", "null", "panic"]
        feature_keywords = ["add", "feature", "support", "implement", "new"]
        docs_keywords = ["doc", "readme", "documentation", "文档"]

        if any(kw in combined for kw in bug_keywords):
            labels.append("bug")
        elif any(kw in combined for kw in feature_keywords):
            labels.append("feature")
        elif any(kw in combined for kw in docs_keywords):
            labels.append("docs")

        return list(set(labels))  # 去重
