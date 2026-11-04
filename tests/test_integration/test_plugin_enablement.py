# tests/test_integration/test_plugin_enablement.py
"""发现 != 启用:插件先被找到,再决定要不要加载。"""

from __future__ import annotations

import textwrap

from engine.plugin_manager.registry import PluginRegistry, plugin_enabled

PLUGIN_PY = textwrap.dedent(
    '''
    from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType


    class Demo(PluginBase):
        def info(self):
            return PluginInfo(name="demo", version="1", type=PluginType.ACTION, description="d")

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
    '''
)


def _make_plugin(root, default_enabled=True):
    pkg = root / "demo"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "plugin.py").write_text(PLUGIN_PY, encoding="utf-8")
    flag = "" if default_enabled else "default_enabled: false\n"
    (pkg / "plugin.yaml").write_text(
        "name: demo\nversion: 1.0.0\ntype: action\ndescription: d\n"
        "class_name: Demo\n" + flag,
        encoding="utf-8",
    )
    return root


def test_default_follows_manifest(monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    assert plugin_enabled("x", True) is True
    assert plugin_enabled("x", False) is False


def test_disabled_list(monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.setenv("PLUGINS_DISABLED", "a,b")
    assert plugin_enabled("a") is False
    assert plugin_enabled("c") is True


def test_enabled_whitelist_wins(monkeypatch):
    monkeypatch.setenv("PLUGINS_ENABLED", "a")
    assert plugin_enabled("a", False) is True
    assert plugin_enabled("b") is False


def test_discovery_loads_enabled_plugin(tmp_path, monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    root = _make_plugin(tmp_path)
    assert PluginRegistry().discover(builtin_dir=root) == 1


def test_discovery_skips_opt_in_plugin_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    root = _make_plugin(tmp_path, default_enabled=False)
    assert PluginRegistry().discover(builtin_dir=root) == 0


def test_whitelist_reenables_opt_in_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGINS_ENABLED", "demo")
    root = _make_plugin(tmp_path, default_enabled=False)
    assert PluginRegistry().discover(builtin_dir=root) == 1
