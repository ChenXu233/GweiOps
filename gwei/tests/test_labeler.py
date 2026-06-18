# tests/test_labeler.py
import pytest
from src.services.labeler import LabelGenerator, LabelMapping


def test_label_mapping_defaults():
    mapping = LabelMapping()
    assert "lexer" in mapping.keywords
    assert "parser" in mapping.keywords
    assert "type-checker" in mapping.keywords


def test_label_mapping_custom():
    mapping = LabelMapping.from_config({
        "labels": {
            "mapping": {
                "frontend": ["react", "vue", "css"],
                "backend": ["api", "database", "server"],
            }
        }
    })
    assert "frontend" in mapping.keywords
    assert "react" in mapping.keywords["frontend"]


def test_generate_labels_bug():
    generator = LabelGenerator()
    labels = generator.generate(
        title="Parser crash on null input",
        body="When input is null, the parser throws a segfault error",
    )
    assert "bug" in labels
    assert "parser" in labels


def test_generate_labels_feature():
    generator = LabelGenerator()
    labels = generator.generate(
        title="Add support for JSON output",
        body="It would be great to have JSON output format for the lexer",
    )
    assert "feature" in labels
    assert "lexer" in labels


def test_generate_labels_docs():
    generator = LabelGenerator()
    labels = generator.generate(
        title="Update README with examples",
        body="The documentation is missing usage examples",
    )
    assert "docs" in labels


def test_generate_labels_multiple():
    generator = LabelGenerator()
    labels = generator.generate(
        title="Fix parser and lexer crash",
        body="Both parser and lexer crash on empty input",
    )
    assert "parser" in labels
    assert "lexer" in labels
    assert "bug" in labels


def test_generate_labels_empty():
    generator = LabelGenerator()
    labels = generator.generate(title="", body="")
    assert labels == []
