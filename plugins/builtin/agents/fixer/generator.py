# src/services/patch_generator.py
from dataclasses import dataclass


@dataclass
class Patch:
    type: str  # HOTFIX, PROPER, REFACTOR
    diff: str
    risk: str
    description: str


class PatchGenerator:
    """生成修复方案。"""

    def generate_hotfix(
        self,
        issue_title: str,
        issue_body: str,
        file_path: str,
        error_info: str = "",
    ) -> Patch:
        """生成快速修复方案。"""
        diff = f"""--- a/{file_path}
+++ b/{file_path}
@@ -1,3 +1,5 @@
+# Quick fix for: {issue_title}
+# TODO: This is a temporary fix
 def process_input(data):
+    if data is None:
+        return None
     return data.process()"""

        return Patch(
            type="HOTFIX",
            diff=diff,
            risk="Low",
            description=f"Quick fix for: {issue_title}. Minimal change to prevent crash.",
        )

    def generate_proper_fix(
        self,
        issue_title: str,
        issue_body: str,
        file_path: str,
        root_cause: str = "",
    ) -> Patch:
        """生成源头修复方案。"""
        diff = f"""--- a/{file_path}
+++ b/{file_path}
@@ -1,3 +1,8 @@
+# Proper fix for: {issue_title}
+# Root cause: {root_cause or 'Input validation missing'}
 def process_input(data):
+    if not isinstance(data, ExpectedType):
+        raise TypeError(f"Expected {{ExpectedType}}, got {{type(data)}}")
+    if data is None:
+        raise ValueError("Input cannot be None")
     return data.process()"""

        return Patch(
            type="PROPER",
            diff=diff,
            risk="Medium",
            description=f"Root cause fix for: {issue_title}. Adds proper input validation.",
        )

    def generate_refactor(
        self,
        issue_title: str,
        issue_body: str,
        file_path: str,
        improvement: str = "",
    ) -> Patch:
        """生成重构修复方案。"""
        diff = f"""--- a/{file_path}
+++ b/{file_path}
@@ -1,3 +1,12 @@
+# Refactor for: {issue_title}
+# Improvement: {improvement or 'Better error handling and validation'}
-class InputProcessor:
-    def process(self, data):
-        return data.process()
+class InputProcessor:
+    def __init__(self, validator=None):
+        self.validator = validator or DefaultValidator()
+
+    def process(self, data):
+        validated = self.validator.validate(data)
+        return validated.process()"""

        return Patch(
            type="REFACTOR",
            diff=diff,
            risk="High",
            description=f"Code refactoring for: {issue_title}. Long-term maintainability improvement.",
        )

    def generate_all(
        self,
        issue_title: str,
        issue_body: str,
        file_path: str,
        context: dict | None = None,
    ) -> list[Patch]:
        """生成所有三种修复方案。"""
        return [
            self.generate_hotfix(issue_title, issue_body, file_path),
            self.generate_proper_fix(issue_title, issue_body, file_path),
            self.generate_refactor(issue_title, issue_body, file_path),
        ]
