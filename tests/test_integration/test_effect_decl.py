# tests/test_integration/test_effect_decl.py
"""效果声明:核心解析、加载期拒绝、并列提供者报错。"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType
from engine.plugin_manager.manifest import EffectDecl, Manifest, ManifestError
from engine.plugin_manager.registry import PluginRegistry


BASE = {
    "name": "p",
    "version": "1.0.0",
    "type": "action",
    "description": "d",
    "class_name": "P",
    "capabilities": ["demo.effect"],
}


def _write(tmp_path, extra: dict) -> pathlib.Path:
    data = dict(BASE)
    data.update(extra)
    path = tmp_path / "plugin.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


GOOD = {
    "effects": {
        "demo.effect": {
            "execute": {"task": "run"},
            "undo": {"task": "undo", "kind": "symmetric"},
            "window": {"read": "present"},
            "verify": [{"query": "exists", "expect": "true"}],
        }
    }
}


def test_good_effect_parsed(tmp_path):
    manifest = Manifest.from_yaml(_write(tmp_path, GOOD))
    decl = manifest.effects["demo.effect"]
    assert isinstance(decl, EffectDecl)
    assert decl.undo_kind == "symmetric"
    assert decl.window_read == "present"


def test_missing_undo_rejected(tmp_path):
    broken = {"effects": {"demo.effect": {
        "execute": {"task": "run"},
        "window": {"read": "present"},
        "verify": [{"query": "q", "expect": "true"}],
    }}}
    with pytest.raises(ManifestError, match="undo.task"):
        Manifest.from_yaml(_write(tmp_path, broken))


def test_bad_undo_kind_rejected(tmp_path):
    broken = {"effects": {"demo.effect": {
        "execute": {"task": "run"},
        "undo": {"task": "u", "kind": "magic"},
        "window": {"read": "present"},
        "verify": [{"query": "q", "expect": "true"}],
    }}}
    with pytest.raises(ManifestError, match="undo.kind"):
        Manifest.from_yaml(_write(tmp_path, broken))


def test_missing_window_rejected(tmp_path):
    broken = {"effects": {"demo.effect": {
        "execute": {"task": "run"},
        "undo": {"task": "u"},
        "verify": [{"query": "q", "expect": "true"}],
    }}}
    with pytest.raises(ManifestError, match="window.read"):
        Manifest.from_yaml(_write(tmp_path, broken))


def test_empty_verify_rejected(tmp_path):
    broken = {"effects": {"demo.effect": {
        "execute": {"task": "run"},
        "undo": {"task": "u"},
        "window": {"read": "present"},
        "verify": [],
    }}}
    with pytest.raises(ManifestError, match="verify"):
        Manifest.from_yaml(_write(tmp_path, broken))


def test_verify_rule_needs_expect(tmp_path):
    broken = {"effects": {"demo.effect": {
        "execute": {"task": "run"},
        "undo": {"task": "u"},
        "window": {"read": "present"},
        "verify": [{"query": "q"}],
    }}}
    with pytest.raises(ManifestError, match="query, expect"):
        Manifest.from_yaml(_write(tmp_path, broken))


class Fake(PluginBase):
    def __init__(self, binding="b", tenant=""):
        self.binding = binding
        self.tenant = tenant

    def info(self):
        return PluginInfo(name="p", version="1", type=PluginType.ACTION, description="d")

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self):
        return True

    async def handle_event(self, event, data):
        return {}

    async def execute_task(self, task, params):
        return {}


def test_effect_decl_exposed_by_registry(tmp_path):
    manifest = Manifest.from_yaml(_write(tmp_path, GOOD))
    reg = PluginRegistry()
    reg.register(manifest, Fake(binding="b", tenant=""))
    provider, decl = reg.effect_decl("demo.effect", tenant="t", binding="b")
    assert decl.capability == "demo.effect"
    assert provider is reg.get("p")


def test_effect_requires_capability_entry(tmp_path):
    data = dict(BASE)
    data.pop("capabilities")
    data.update(GOOD)
    path = tmp_path / "plugin.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="未列入 capabilities"):
        PluginRegistry().register(Manifest.from_yaml(path), Fake())


def test_tie_without_priority_is_an_error(tmp_path):
    manifest = Manifest.from_yaml(_write(tmp_path, GOOD))
    reg = PluginRegistry()
    reg.register(manifest, Fake(binding="b"), key="one")
    reg.register(manifest, Fake(binding="b"), key="two")
    with pytest.raises(LookupError, match="并列"):
        reg.effect_decl("demo.effect", tenant="", binding="b")
