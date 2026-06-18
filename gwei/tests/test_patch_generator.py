# tests/test_patch_generator.py
import pytest
from src.services.patch_generator import PatchGenerator, Patch


def test_generator_init():
    generator = PatchGenerator()
    assert generator is not None


def test_generate_hotfix():
    generator = PatchGenerator()
    patch = generator.generate_hotfix(
        issue_title="Parser crash",
        issue_body="Crash on null input",
        file_path="src/parser.py",
        error_info="NullPointerException",
    )

    assert patch.type == "HOTFIX"
    assert patch.risk == "Low"
    assert "null" in patch.diff.lower() or "none" in patch.diff.lower()


def test_generate_proper_fix():
    generator = PatchGenerator()
    patch = generator.generate_proper_fix(
        issue_title="Parser crash",
        issue_body="Crash on null input",
        file_path="src/parser.py",
        root_cause="Missing null check",
    )

    assert patch.type == "PROPER"
    assert patch.risk == "Medium"
    assert len(patch.diff) > 0


def test_generate_refactor():
    generator = PatchGenerator()
    patch = generator.generate_refactor(
        issue_title="Parser crash",
        issue_body="Crash on null input",
        file_path="src/parser.py",
        improvement="Add input validation",
    )

    assert patch.type == "REFACTOR"
    assert patch.risk == "High"
    assert len(patch.diff) > 0


def test_generate_all_patches():
    generator = PatchGenerator()
    patches = generator.generate_all(
        issue_title="Parser crash",
        issue_body="Crash on null input",
        file_path="src/parser.py",
    )

    assert len(patches) == 3
    types = [p.type for p in patches]
    assert "HOTFIX" in types
    assert "PROPER" in types
    assert "REFACTOR" in types


def test_patch_dataclass():
    patch = Patch(
        type="HOTFIX",
        diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
        risk="Low",
        description="Quick fix",
    )

    assert patch.type == "HOTFIX"
    assert "old" in patch.diff
    assert patch.risk == "Low"


def test_generate_patches_with_context():
    generator = PatchGenerator()
    patches = generator.generate_all(
        issue_title="Add JSON support",
        issue_body="Need JSON output format",
        file_path="src/output.py",
        context={"language": "python", "framework": "fastapi"},
    )

    assert len(patches) == 3
    for patch in patches:
        assert len(patch.diff) > 0
