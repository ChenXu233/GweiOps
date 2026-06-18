# src/services/code_analyzer.py
import ast
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    has_syntax_error: bool = False
    error_message: str | None = None


class CodeAnalyzer:
    """代码分析器。解析代码结构。"""

    def analyze(self, code: str, language: str = "python") -> AnalysisResult:
        """分析代码结构。"""
        if language != "python":
            return AnalysisResult()

        if not code.strip():
            return AnalysisResult()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return AnalysisResult(
                has_syntax_error=True,
                error_message=str(e),
            )

        functions = []
        classes = []
        methods = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 检查是否是类方法
                if isinstance(node, ast.ClassDef):
                    methods.append(node.name)
                else:
                    functions.append(node.name)

            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
                # 收集类中的方法
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.append(item.name)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])

        return AnalysisResult(
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
        )
