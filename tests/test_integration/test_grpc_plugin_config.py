# tests/test_integration/test_grpc_plugin_config.py
"""进程外插件的配置:清单声明、核心登记、推给对面。

进程外插件读不到核心的环境变量与业务库,`config.get_scope_config()` 在它那一侧
什么都不返回。所以配置只有一条路可走:核心把它送过去。这里的用例钉的是这条路——
以及"送不过去时说得清楚"这件事。
"""

from __future__ import annotations

import asyncio
from concurrent import futures

import pytest

grpc = pytest.importorskip("grpc")

from engine.plugin_manager.base import PluginType
from engine.plugin_manager.grpc_loader import GrpcPluginProxy
from engine.plugin_manager.grpc_proto import plugin_pb2_grpc
from engine.plugin_manager.grpc_server import build_servicer
from engine.plugin_manager.manifest import Manifest, ManifestError
from engine.plugin_manager.registry import PluginRegistry
from engine.shared.config import config


class ConfigurablePlugin:
    """收配置的进程外插件。收到什么记下来,测试据此判断推没推到。"""

    def __init__(self, *, reject: str = "") -> None:
        self.received: dict[str, dict[str, str]] = {}
        self.missing: dict[str, list[str]] = {}
        self.reject = reject  # 非空 = 收到该 scope 就拒

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: dict) -> dict:
        # 顺带把"插件此刻手里有什么"暴露出来,方便断言
        return {
            "settings": self.received.get("adapter-acme", {}),
            "missing": self.missing.get("adapter-acme", []),
        }

    async def configure(self, scope: str, values: dict, missing: list[str]) -> None:
        if self.reject == scope:
            raise ValueError("我不认该 scope")
        self.received[scope] = dict(values)
        self.missing[scope] = list(missing)


@pytest.fixture()
def remote():
    plugin = ConfigurablePlugin()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(build_servicer(plugin), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield f"127.0.0.1:{port}", plugin
    finally:
        server.stop(0)


@pytest.fixture()
def clean_scopes():
    before = set(config._scopes)
    yield
    for name in list(config._scopes):
        if name not in before:
            config._scopes.pop(name, None)


def _manifest(**kw) -> Manifest:
    from engine.plugin_manager.manifest import ScopeDecl

    base = dict(
        name="adapter-acme",
        version="1.0.0",
        type=PluginType.ADAPTER,
        description="进程外适配器",
        class_name="",
        capabilities=["acme.read"],
        tasks={"acme.read": "read"},
        scopes={
            "adapter-acme": ScopeDecl(
                name="adapter-acme",
                prefix="ACME_",
                required=("token",),
                optional=("base_url",),
            )
        },
    )
    base.update(kw)
    return Manifest(**base)


def test_scope_block_is_declared_in_the_manifest(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: adapter-acme\nversion: 1.0.0\ntype: adapter\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ncapabilities: [acme.read]\n"
        "scopes:\n"
        "  adapter-acme:\n"
        "    prefix: ACME_\n"
        "    required: [token]\n"
        "    optional: [base_url]\n",
        encoding="utf-8",
    )
    manifest = Manifest.from_yaml(path)
    decl = manifest.scopes["adapter-acme"]
    assert decl.prefix == "ACME_"
    assert decl.required == ("token",)
    assert decl.optional == ("base_url",)


def test_a_key_cannot_be_both_required_and_optional(tmp_path):
    """必填与可选只能挑一个:两边都写,人不知道该不该填。"""
    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: adapter-acme\nversion: 1.0.0\ntype: adapter\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\n"
        "scopes:\n"
        "  adapter-acme:\n"
        "    required: [token]\n"
        "    optional: [token]\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="同时在 required"):
        Manifest.from_yaml(path)


def test_malformed_scopes_block_is_rejected(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: adapter-acme\nversion: 1.0.0\ntype: adapter\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\n"
        "scopes:\n"
        "  adapter-acme:\n"
        "    required: token\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="必须是字符串列表"):
        Manifest.from_yaml(path)


def test_discovery_registers_the_declared_scope(tmp_path, monkeypatch, clean_scopes):
    """清单声明的 scope 进配置表:否则设置页列不出字段,也说不出缺什么。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    plug = tmp_path / "adapter-acme"
    plug.mkdir()
    (plug / "plugin.yaml").write_text(
        "name: adapter-acme\nversion: 1.0.0\ntype: adapter\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ncapabilities: [acme.read]\n"
        "scopes:\n"
        "  adapter-acme:\n"
        "    prefix: ACME_\n"
        "    required: [token]\n",
        encoding="utf-8",
    )
    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 1
    assert config.get_scope("adapter-acme") is not None
    # 没填就没填:缺项要如实报出来,并且报出要补的环境变量名
    assert config.validate_scope("adapter-acme") == ["ACME_TOKEN"]


def test_a_scope_registered_in_code_is_not_overwritten(tmp_path, monkeypatch, clean_scopes):
    """进程内插件在代码里注册过同名 scope:代码声明优先于清单粗声明。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    config.register_scope("adapter-acme", "CODE_", required=["token"])
    plug = tmp_path / "adapter-acme"
    plug.mkdir()
    (plug / "plugin.yaml").write_text(
        "name: adapter-acme\nversion: 1.0.0\ntype: adapter\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\n"
        "scopes:\n"
        "  adapter-acme:\n"
        "    prefix: ACME_\n",
        encoding="utf-8",
    )
    PluginRegistry().discover(builtin_dir=tmp_path)
    assert config.get_scope("adapter-acme").prefix == "CODE_"


def test_config_is_pushed_to_the_remote_plugin(remote, monkeypatch, clean_scopes):
    """启动之后把值推下去;远端手里因此真有它的配置。"""
    target, plugin = remote
    monkeypatch.setenv("ACME_TOKEN", "tok-123")
    monkeypatch.delenv("ACME_BASE_URL", raising=False)

    manifest = _manifest(endpoint=target)
    reg = PluginRegistry()
    reg.register(manifest, GrpcPluginProxy(manifest, target))
    asyncio.run(reg.launch())

    assert plugin.received["adapter-acme"] == {"token": "tok-123"}
    # 空值不下发:推一个空串等于教远端"这一项是空字符串",与"还没填"不是一回事
    assert "base_url" not in plugin.received["adapter-acme"]


def test_missing_required_field_is_named_to_the_plugin(remote, monkeypatch, clean_scopes):
    """缺哪一项要一起告诉远端:它才能在自己的日志或页面上说清楚。"""
    target, plugin = remote
    monkeypatch.delenv("ACME_TOKEN", raising=False)

    manifest = _manifest(endpoint=target)
    reg = PluginRegistry()
    reg.register(manifest, GrpcPluginProxy(manifest, target))
    asyncio.run(reg.launch())

    assert plugin.missing["adapter-acme"] == ["ACME_TOKEN"]


def test_repush_after_a_config_change(remote, monkeypatch, clean_scopes):
    """改完配置重推一次:不用重启进程,远端拿到的是新值。"""
    target, plugin = remote
    monkeypatch.setenv("ACME_TOKEN", "old")
    manifest = _manifest(endpoint=target)
    reg = PluginRegistry()
    reg.register(manifest, GrpcPluginProxy(manifest, target))
    asyncio.run(reg.launch())
    assert plugin.received["adapter-acme"]["token"] == "old"

    monkeypatch.setenv("ACME_TOKEN", "new")
    failures = asyncio.run(reg.push_config("adapter-acme"))
    assert failures == {}
    assert plugin.received["adapter-acme"]["token"] == "new"


def test_push_only_touches_plugins_that_declare_the_scope(remote, monkeypatch, clean_scopes):
    """改一项配置不该让所有插件的连接都抖一下。"""
    target, plugin = remote
    monkeypatch.setenv("ACME_TOKEN", "tok")

    matched = _manifest(endpoint=target)
    other = Manifest(
        name="adapter-other",
        version="1.0.0",
        type=PluginType.ADAPTER,
        description="别的适配器",
        class_name="",
        capabilities=["other.read"],
    )
    reg = PluginRegistry()
    reg.register(matched, GrpcPluginProxy(matched, target))
    reg.register(other, GrpcPluginProxy(other, target))
    asyncio.run(reg.launch())

    plugin.received.clear()
    asyncio.run(reg.push_config("no-such-scope"))
    assert plugin.received == {}

    asyncio.run(reg.push_config("adapter-acme"))
    assert "adapter-acme" in plugin.received


def test_a_plugin_that_refuses_config_is_reported_not_swallowed(
    remote, monkeypatch, clean_scopes
):
    """插件拒收要说出来:它手里是旧配置,这件事不能悄悄过去。"""
    target, plugin = remote
    plugin.reject = "adapter-acme"
    monkeypatch.setenv("ACME_TOKEN", "tok")

    manifest = _manifest(endpoint=target)
    reg = PluginRegistry()
    reg.register(manifest, GrpcPluginProxy(manifest, target))
    asyncio.run(reg.launch())

    state = [s for s in reg.states() if s.manifest.name == "adapter-acme"][0]
    # 插件在跑,差别只是它手里是旧配置——所以不能记成"启动失败"
    assert state.enabled is True
    assert "配置没推下去" in state.error
    assert "我不认该 scope" in state.error


def test_a_plugin_without_configure_is_left_alone(remote, monkeypatch, clean_scopes):
    """没实现 configure 的插件不推:它读得到自己的配置,再送一份只是两份会漂移的事实。"""
    target, _plugin = remote
    monkeypatch.setenv("ACME_TOKEN", "tok")

    class Plain:
        async def on_startup(self) -> None: ...
        async def on_shutdown(self) -> None: ...
        async def health_check(self) -> bool: return True
        async def handle_event(self, event, data): return {}
        async def execute_task(self, task, params): return {}

    manifest = _manifest()
    reg = PluginRegistry()
    reg.register(manifest, Plain())
    # 不炸就行:返回值是"推送失败说明",没有 configure 就没有失败
    assert asyncio.run(reg.push_config("adapter-acme")) == {}


def test_proxy_reports_a_refusal(remote, monkeypatch, clean_scopes):
    """代理把远端的拒收翻成 GrpcPluginError,不让调用方看见裸 grpc 异常。"""
    from engine.plugin_manager.grpc_loader import GrpcPluginError

    target, plugin = remote
    plugin.reject = "adapter-acme"
    proxy = GrpcPluginProxy(_manifest(endpoint=target), target)
    with pytest.raises(GrpcPluginError, match="被拒"):
        asyncio.run(proxy.configure("adapter-acme", {"token": "t"}, []))
