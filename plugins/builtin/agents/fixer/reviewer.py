# src/services/code_reviewer.py
import ast
from dataclasses import dataclass, field


@dataclass
class ReviewIssue:
    severity: str  # error, warning, info
    message: str
    line: int | None = None
    file: str | None = None


@dataclass
class ReviewResult:
    issues: list[ReviewIssue]
    score: int
    summary: str


class CodeReviewer:
    """代码审查器。检查代码质量。"""

    def review(self, code: str, language: str = "python") -> ReviewResult:
        """审查代码质量。"""
        if language != "python":
            return ReviewResult(issues=[], score=100, summary="Language not supported")

        if not code.strip():
            return ReviewResult(issues=[], score=100, summary="Empty code")

        issues = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ReviewResult(
                issues=[ReviewIssue(severity="error", message=f"Syntax error: {e}")],
                score=0,
                summary="Syntax error",
            )

        # 检查各种问题
        issues.extend(self._check_missing_type_hints(tree))
        issues.extend(self._check_bare_except(tree))
        issues.extend(self._check_long_functions(tree))
        issues.extend(self._check_unused_imports(tree, code))

        # 计算分数
        score = max(0, 100 - len(issues) * 10)

        # 生成摘要
        if not issues:
            summary = "No issues found"
        else:
            errors = sum(1 for i in issues if i.severity == "error")
            warnings = sum(1 for i in issues if i.severity == "warning")
            summary = f"Found {errors} errors, {warnings} warnings"

        return ReviewResult(issues=issues, score=score, summary=summary)

    def _check_missing_type_hints(self, tree: ast.AST) -> list[ReviewIssue]:
        """检查缺少类型提示。"""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 只检查有 return 语句且返回非 None 值的函数
                has_value_return = any(
                    isinstance(child, ast.Return) and child.value is not None
                    for child in ast.walk(node)
                )
                if has_value_return and node.returns is None:
                    issues.append(ReviewIssue(
                        severity="warning",
                        message=f"Missing return type hint for function '{node.name}'",
                        line=node.lineno,
                    ))

                # 检查参数类型（跳过 self/cls）
                for arg in node.args.args:
                    if arg.arg in ("self", "cls"):
                        continue
                    if arg.annotation is None:
                        issues.append(ReviewIssue(
                            severity="warning",
                            message=f"Missing type hint for parameter '{arg.arg}' in '{node.name}'",
                            line=node.lineno,
                        ))

        return issues

    def _check_bare_except(self, tree: ast.AST) -> list[ReviewIssue]:
        """检查裸 except。"""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(ReviewIssue(
                    severity="warning",
                    message="Bare except clause - should specify exception type",
                    line=node.lineno,
                ))

        return issues

    def _check_long_functions(self, tree: ast.AST) -> list[ReviewIssue]:
        """检查过长的函数。"""
        issues = []
        max_lines = 50

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > max_lines:
                        issues.append(ReviewIssue(
                            severity="warning",
                            message=f"Function '{node.name}' is too long ({length} lines, max {max_lines})",
                            line=node.lineno,
                        ))

        return issues

    def _check_unused_imports(self, tree: ast.AST, code: str) -> list[ReviewIssue]:
        """检查未使用的导入。"""
        issues = []
        imports = []
        used_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imports.append((name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports.append((name, node.lineno))
            elif isinstance(node, ast.Name):
                used_names.add(node.id)

        for name, line in imports:
            if name not in used_names and name != "*":
                issues.append(ReviewIssue(
                    severity="info",
                    message=f"Unused import: '{name}'",
                    line=line,
                ))

        return issues
