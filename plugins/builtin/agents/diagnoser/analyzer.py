# src/services/code_analyzer.py
import ast
import re
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
    """代码分析器。解析代码结构。支持多语言。"""

    def analyze(self, code: str, language: str = "python") -> AnalysisResult:
        """分析代码结构。"""
        if not code.strip():
            return AnalysisResult()

        analyzers = {
            "python": self._analyze_python,
            "javascript": self._analyze_javascript,
            "typescript": self._analyze_typescript,
            "java": self._analyze_java,
            "go": self._analyze_go,
            "rust": self._analyze_rust,
        }

        analyzer = analyzers.get(language)
        if not analyzer:
            return AnalysisResult()

        return analyzer(code)

    def _analyze_python(self, code: str) -> AnalysisResult:
        """分析 Python 代码。"""
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
                if isinstance(node, ast.ClassDef):
                    methods.append(node.name)
                else:
                    functions.append(node.name)

            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
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

    def _analyze_javascript(self, code: str) -> AnalysisResult:
        """分析 JavaScript 代码。"""
        functions = []
        classes = []
        methods = []
        imports = []

        # 匹配函数声明
        func_pattern = r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:function|\([^)]*\)\s*=>))'
        for match in re.finditer(func_pattern, code):
            name = match.group(1) or match.group(2)
            if name:
                functions.append(name)

        # 匹配类声明
        class_pattern = r'class\s+(\w+)'
        for match in re.finditer(class_pattern, code):
            classes.append(match.group(1))

        # 匹配方法
        method_pattern = r'(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{'
        for match in re.finditer(method_pattern, code):
            name = match.group(1)
            if name not in ['if', 'for', 'while', 'switch', 'catch']:
                methods.append(name)

        # 匹配导入
        import_pattern = r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(import_pattern, code):
            imports.append(match.group(1))

        require_pattern = r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
        for match in re.finditer(require_pattern, code):
            imports.append(match.group(1))

        return AnalysisResult(
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
        )

    def _analyze_typescript(self, code: str) -> AnalysisResult:
        """分析 TypeScript 代码。"""
        # TypeScript 语法与 JavaScript 类似，使用相同的分析器
        return self._analyze_javascript(code)

    def _analyze_java(self, code: str) -> AnalysisResult:
        """分析 Java 代码。"""
        functions = []
        classes = []
        methods = []
        imports = []

        # 匹配类声明
        class_pattern = r'(?:public\s+)?(?:abstract\s+)?(?:class|interface)\s+(\w+)'
        for match in re.finditer(class_pattern, code):
            classes.append(match.group(1))

        # 匹配方法
        method_pattern = r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{'
        for match in re.finditer(method_pattern, code):
            name = match.group(1)
            if name not in ['if', 'for', 'while', 'switch', 'catch', 'class']:
                methods.append(name)

        # 匹配导入
        import_pattern = r'import\s+(?:static\s+)?([^;]+);'
        for match in re.finditer(import_pattern, code):
            imports.append(match.group(1).strip())

        return AnalysisResult(
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
        )

    def _analyze_go(self, code: str) -> AnalysisResult:
        """分析 Go 代码。"""
        functions = []
        classes = []
        methods = []
        imports = []

        # 匹配函数声明
        func_pattern = r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\('
        for match in re.finditer(func_pattern, code):
            functions.append(match.group(1))

        # 匹配结构体
        struct_pattern = r'type\s+(\w+)\s+struct'
        for match in re.finditer(struct_pattern, code):
            classes.append(match.group(1))

        # 匹配导入
        import_pattern = r'import\s+(?:\(\s*)?[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(import_pattern, code):
            imports.append(match.group(1))

        return AnalysisResult(
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
        )

    def _analyze_rust(self, code: str) -> AnalysisResult:
        """分析 Rust 代码。"""
        functions = []
        classes = []
        methods = []
        imports = []

        # 匹配函数声明
        func_pattern = r'fn\s+(\w+)\s*(?:<[^>]*>)?\s*\('
        for match in re.finditer(func_pattern, code):
            functions.append(match.group(1))

        # 匹配结构体
        struct_pattern = r'(?:pub\s+)?struct\s+(\w+)'
        for match in re.finditer(struct_pattern, code):
            classes.append(match.group(1))

        # 匹配 impl 方法
        impl_pattern = r'impl\s+(\w+)'
        for match in re.finditer(impl_pattern, code):
            classes.append(match.group(1))

        # 匹配 use 导入
        use_pattern = r'use\s+([^;]+);'
        for match in re.finditer(use_pattern, code):
            imports.append(match.group(1).strip())

        return AnalysisResult(
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
        )
