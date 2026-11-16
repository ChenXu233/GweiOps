# tests/test_integration/test_plugin_enablement_runtime.py
"""运行期启停:控制台上的开关必须真的改行为,不是只改一行配置。

覆盖四件在 Issue #14 里被实测出来的事:

1. 关闭插件后,主链路不再偷偷直连它(开关不是装饰);
2. 未启用的插件也能被列出来并打开(`发现 ≠ 启用` 要看得见);
3. 启停决定活过重启(写在库里,启动时装回);
4. 内置插件声明的能力真的调得通(任务名映射对得上实现)。
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest

from engine.plugin_manager.registry import PluginRegistry


PLUGIN_PY = """
from engine.plugin_manager.base import PluginBase, PluginType


class Demo(PluginBase):

    async def on_startup(self):
        self.started = True

    async def on_shutdown(self):
        self.stopped = True

    async def health_check(self):
        return True

    async def handle_event(self, event, data):
        return {}

    async def execute_task(self, task, params):
        return {"task": task}
"""


def _write_plugin(root, name="demo", *, default_enabled=True, capabilities=("demo.read",)):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "plugin.py").write_text(textwrap.dedent(PLUGIN_PY), encoding="utf-8")
    caps = "".join(f"  - {c}\n" for c in capabilities)
    (pkg / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ntype: action\ndescription: d\n"
        f"class_name: Demo\n"
        + ("" if default_enabled else "default_enabled: false\n")
        + ("capabilities:\n" + caps if capabilities else ""),
        encoding="utf-8",
    )


def test_listed_even_when_not_enabled(tmp_path, monkeypatch):
    """未启用的插件也在名单里,控制台才有地方把它打开。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "demo-hidden", default_enabled=False)

    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 0

    states = reg.states()
    assert [s.manifest.name for s in states] == ["demo-hidden"]
    assert states[0].enabled is False
    assert states[0].reason == "清单声明 default_enabled: false"
    # 发现 ≠ 启用:声明在(available 里),能力却解析不到
    assert [m.name for m in reg.available()] == ["demo-hidden"]
    assert reg.best_capability_provider("demo.read") is None


def test_enable_then_disable_changes_resolution(tmp_path, monkeypatch):
    """打开就能解析到、调得通;关掉立刻解析不到。都不重启进程。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "demo-toggle", default_enabled=False)

    reg = PluginRegistry()
    reg.discover(builtin_dir=tmp_path)
    asyncio.run(reg.launch())

    asyncio.run(reg.enable("demo-toggle"))
    assert reg.get("demo-toggle") is not None
    assert asyncio.run(reg.run_capability("demo.read", {})) == {"task": "demo_read"}

    asyncio.run(reg.disable("demo-toggle"))
    assert reg.get("demo-toggle") is None
    assert reg.best_capability_provider("demo.read") is None
    # 摘干净了:事件、能力、Hook 索引里都不该留残影
    assert "demo-toggle" not in reg.names()


def test_disable_removes_all_indexes(tmp_path, monkeypatch):
    """停用不是打个标记:索引里留着它,就等于它还在流程里。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    pkg = tmp_path / "demo-index"
    pkg.mkdir()
    (pkg / "plugin.py").write_text(textwrap.dedent(PLUGIN_PY), encoding="utf-8")
    (pkg / "plugin.yaml").write_text(
        "name: demo-index\nversion: 1.0.0\ntype: action\ndescription: d\nclass_name: Demo\n"
        "capabilities:\n  - demo.read\n"
        "triggers:\n  - type: event\n    events: [demo.ping]\n"
        "hooks:\n  subscribe:\n    - point: comment.posting\n      mode: veto\n",
        encoding="utf-8",
    )
    reg = PluginRegistry()
    reg.discover(builtin_dir=tmp_path)
    assert reg.instances_for_event("demo.ping")
    assert reg.hook_subscribers("comment.posting")

    asyncio.run(reg.disable("demo-index"))
    assert reg.instances_for_event("demo.ping") == []
    assert reg.hook_subscribers("comment.posting") == []
    assert reg.best_capability_provider("demo.read") is None


def test_decisions_survive_restart(tmp_path, monkeypatch):
    """启停写进库之后重启:装回决定,按它加载。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "demo-restart", default_enabled=True)

    reg = PluginRegistry()
    reg.set_decisions({"demo-restart": False})  # 相当于上次在控制台上关掉了它
    assert reg.discover(builtin_dir=tmp_path) == 0
    assert reg.states()[0].reason == "运行期停用"

    reg2 = PluginRegistry()
    reg2.set_decisions({"demo-restart": True})
    assert reg2.discover(builtin_dir=tmp_path) == 1


def test_runtime_decision_beats_env_whitelist(tmp_path, monkeypatch):
    """控制台写入的启停决定(plugin-enablement scope)压过部署环境变量。"""
    monkeypatch.setenv("PLUGINS_ENABLED", "demo-env")
    _write_plugin(tmp_path, "demo-env")
    reg = PluginRegistry()
    reg.set_decisions({"demo-env": False})
    assert reg.discover(builtin_dir=tmp_path) == 0


def test_whitelist_typo_is_reported(tmp_path, monkeypatch, caplog):
    """白名单写错名字时点名告警,不让日志长得像"部署确实一个插件都不装"。"""
    monkeypatch.setenv("PLUGINS_ENABLED", "demo-typo")
    _write_plugin(tmp_path, "demo-typo-target")
    reg = PluginRegistry()
    with caplog.at_level("WARNING", logger="engine.plugin_manager.registry"):
        assert reg.discover(builtin_dir=tmp_path) == 0
    text = caplog.text
    assert "demo-typo" in text and "没人认领" in text
    assert "demo-typo-target" in text  # 顺带把发现到的插件列出来,人一眼看出是拼错了


def test_duplicate_plugin_name_rejected(tmp_path, monkeypatch, caplog):
    """同名插件出现两次是配置错误,不能静默取一个。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "one")
    _write_plugin(tmp_path, "two")
    # 目录名不同、清单名相同:插件名是唯一标识
    (tmp_path / "two" / "plugin.yaml").write_text(
        (tmp_path / "one" / "plugin.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    reg = PluginRegistry()
    with caplog.at_level("ERROR", logger="engine.plugin_manager.registry"):
        assert reg.discover(builtin_dir=tmp_path) == 1
    assert [s.manifest.name for s in reg.states()] == ["one"]
    assert "出现两次" in caplog.text


# ---------------------------------------------------------------------------
# 内置插件:声明的能力必须调得通
# ---------------------------------------------------------------------------


@pytest.fixture()
def builtin_registry():
    """每个用例前面重新发现一次:conftest 会在用例之间清空生产单例。"""
    from engine.plugin_manager.registry import registry

    registry.discover()
    return registry


@pytest.mark.parametrize(
    "capability,params",
    [
        ("issue.label", {"title": "崩溃", "body": "点一下就没"}),
        ("issue.completeness_check", {"body": ""}),
        ("issue.duplicate_detection", {"title": "t", "body": "b"}),
        ("patch.generate", {"title": "t", "body": "b"}),
        ("code.review", {"code": "print(1)", "language": "python"}),
    ],
)
def test_declared_capability_actually_resolves(builtin_registry, capability, params):
    """清单里写的能力,`run_capability` 必须调得通。

    这条用例钉的是"任务名映射对不上实现":能力名 issue.label 缺省会推成
    issue_label,而实现里叫 label——那时页面列着四个能力,一个都调不通。
    """
    result = asyncio.run(builtin_registry.run_capability(capability, params))
    assert "Unknown task" not in str(result.get("message", "")), result


def test_sensor_declares_task_mapping_for_every_capability(builtin_registry):
    """有能力的插件,每个能力都要有任务名映射或有同名任务,不许靠猜。"""
    for manifest in builtin_registry.manifests():
        if not manifest.capabilities:
            continue
        if manifest.name != "sensor-agent":
            continue
        for capability in manifest.capabilities:
            assert capability in manifest.tasks, f"{capability} 没有任务名映射"


def test_plugin_declarations_have_one_source(builtin_registry):
    """清单是唯一声明源:插件类里不该再有一个 info() 回答同样的问题。

    这条不是风格检查,是"同一事实只有一处"的可判形态:一旦有人把声明写回代码,
    两份就会在下次改清单时漂移,漂移副本没人会去看。
    """
    for manifest in builtin_registry.manifests():
        instance = builtin_registry.get(manifest.name)
        if instance is None:
            continue
        assert not hasattr(instance, "info"), (
            f"{manifest.name} 上还有一个 info() 方法:插件声明只该写在 plugin.yaml 里"
        )
