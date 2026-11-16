# tests/test_integration/test_plugin_data.py
"""插件读库:分级、按租户收口、声明不过就装不上。

这里验的不是"接口返回 200",而是三件事实:

1. 清单里写的 `data.scopes` 决定插件能不能拿到库会话——没声明就没有会话对象;
2. 外部插件与请求 `host`(跨租户)的声明在加载期就被拒,不是运行期才发现;
3. 有会话时,库侧策略把可见范围收到本租户,**忘了写 where 也读不到别人的账**。

第 3 条要真实 Postgres(门控:`GWEI_TEST_DATABASE_URL`),前两条不需要。
"""

from __future__ import annotations

import os
import textwrap

import pytest

from engine.plugin_manager.context import PluginContext, context_for, execute
from engine.plugin_manager.data import DataScopeError, PluginData

PLUGIN_PY = """
from engine.plugin_manager.base import PluginBase


class Demo(PluginBase):

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self):
        return True

    async def handle_event(self, event, data):
        return {}

    async def execute_task(self, task, params, ctx=None):
        self.ctx = ctx
        return {"task": task, "tenant": getattr(ctx, "tenant", "")}
"""


def _write(root, name, *, data_block="", extra=""):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "plugin.py").write_text(textwrap.dedent(PLUGIN_PY), encoding="utf-8")
    (pkg / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ntype: action\ndescription: d\n"
        f"class_name: Demo\ncapabilities:\n  - {name}.read\n" + data_block + extra,
        encoding="utf-8",
    )
    return pkg


# ---------------------------------------------------------------------------
# 清单:写错的名字当场拒
# ---------------------------------------------------------------------------


def test_unknown_data_scope_is_rejected_at_load(tmp_path):
    from engine.plugin_manager.manifest import Manifest, ManifestError

    pkg = _write(tmp_path, "sneaky", data_block="data:\n  scopes: [read:all]\n")
    with pytest.raises(ManifestError) as exc:
        Manifest.from_yaml(pkg / "plugin.yaml")
    assert "read:all" in str(exc.value)


def test_external_plugin_cannot_declare_data_at_all(tmp_path, monkeypatch):
    """外部插件跑在核心进程里,给了库通道就没有边界了。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write(tmp_path, "outside", data_block="data:\n  scopes: [read:own]\n")

    from engine.plugin_manager.registry import PluginRegistry

    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 0
    assert [s.manifest.name for s in reg.states()] == []
    assert reg.best_capability_provider("outside.read") is None


def test_host_scope_is_reserved_for_builtin_plugins(tmp_path):
    """`host`(跨租户)声明得出,但只发给本仓库内置插件。"""
    from engine.plugin_manager.manifest import ManifestError, check_data_scopes

    pkg = _write(tmp_path, "reader", data_block="data:\n  scopes: [host]\n")
    manifest = __import__(
        "engine.plugin_manager.manifest", fromlist=["Manifest"]
    ).Manifest.from_yaml(pkg / "plugin.yaml")

    with pytest.raises(ManifestError) as exc:
        check_data_scopes(pkg / "plugin.yaml", manifest, builtin=False, external=False)
    assert "host" in str(exc.value)
    # 内置插件可以声明
    check_data_scopes(pkg / "plugin.yaml", manifest, builtin=True, external=False)


def test_registry_rejects_data_declaration_for_direct_registration():
    """绕过发现流程直接 register 的外部实例,数据声明照样被拒。"""
    from engine.plugin_manager.base import PluginType
    from engine.plugin_manager.manifest import Manifest, ManifestError
    from engine.plugin_manager.registry import PluginRegistry

    manifest = Manifest(
        name="direct",
        version="1.0.0",
        type=PluginType.ACTION,
        description="d",
        class_name="Demo",
        data_scopes=("read:own",),
    )

    class Instance:
        async def on_startup(self):
            pass

    with pytest.raises(ManifestError):
        PluginRegistry().register(
            manifest, Instance(), source="somepkg.plugin"  # 外挂目录
        )


def test_a_builtin_module_may_register_with_data_scopes():
    from engine.plugin_manager.base import PluginType
    from engine.plugin_manager.manifest import Manifest
    from engine.plugin_manager.registry import PluginRegistry

    manifest = Manifest(
        name="inside",
        version="1.0.0",
        type=PluginType.ACTION,
        description="d",
        class_name="Demo",
        data_scopes=("read:own",),
    )

    class Instance:
        async def on_startup(self):
            pass

    reg = PluginRegistry()
    reg.register(manifest, Instance(), source="plugins.builtin.actions.demo.plugin")
    assert reg.manifest("inside") is not None


# ---------------------------------------------------------------------------
# 通道:没声明就没有会话
# ---------------------------------------------------------------------------


def test_without_a_scope_there_is_no_session():
    data = PluginData(scopes=(), tenant="acme")

    async def go():
        async with data.read():
            return True

    with pytest.raises(DataScopeError):
        __import__("asyncio").run(go())


def test_read_only_scope_cannot_take_a_write_session():
    data = PluginData(scopes=("read:own",), tenant="acme")

    async def go():
        async with data.write():
            return True

    with pytest.raises(DataScopeError):
        __import__("asyncio").run(go())


def test_context_carries_tenant_and_scopes():
    ctx = context_for(tenant="acme", binding="local", scopes=("read:own",), capability="x.read")
    assert isinstance(ctx, PluginContext)
    assert ctx.data.scopes == ("read:own",)
    assert ctx.data.tenant == "acme"
    assert ctx.can("read:own") is True
    assert ctx.can("host") is False


# ---------------------------------------------------------------------------
# 契约:两参与三参 execute_task 都能调
# ---------------------------------------------------------------------------


def test_a_two_argument_execute_task_still_works():
    import asyncio as aio

    class Old:
        async def execute_task(self, task, params):
            return {"task": task, "params": params}

    out = aio.run(execute(Old(), "t", {"a": 1}, context_for(tenant="acme")))
    assert out == {"task": "t", "params": {"a": 1}}


def test_a_three_argument_execute_task_receives_the_context():
    import asyncio as aio

    class New:
        async def execute_task(self, task, params, ctx):
            return {"tenant": ctx.tenant, "scopes": list(ctx.scopes)}

    out = aio.run(execute(New(), "t", {}, context_for(tenant="acme", scopes=("read:own",))))
    assert out == {"tenant": "acme", "scopes": ["read:own"]}


def test_run_capability_passes_the_manifest_scopes(tmp_path, monkeypatch):
    """注册表把被选中插件清单里的 data.scopes 放进 ctx。"""
    import asyncio as aio

    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    # 用一个「内置」模块名让它通过外部插件那道判据
    pkg = _write(tmp_path, "demo", data_block="data:\n  scopes: [read:own]\n")

    from engine.plugin_manager.manifest import Manifest
    from engine.plugin_manager.registry import PluginRegistry

    manifest = Manifest.from_yaml(pkg / "plugin.yaml")
    from engine.plugin_manager.manifest import check_data_scopes

    check_data_scopes(pkg / "plugin.yaml", manifest, builtin=True, external=False)

    import importlib.util

    spec = importlib.util.spec_from_file_location("demo_plugin", pkg / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    reg = PluginRegistry()
    reg.register(manifest, module.Demo())
    out = aio.run(reg.run_capability("demo.read", {}, tenant="acme"))
    assert out == {"task": "demo_read", "tenant": "acme"}


# ---------------------------------------------------------------------------
# 真实库:策略把可见范围收到本租户
# ---------------------------------------------------------------------------

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写了策略的 Postgres",
)


def _sync_engine():
    import sqlalchemy as sa

    return sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])


def _ensure_schema(url: str) -> str:
    """在**独立库**上把迁移跑到头,返回那个库的 URL。

    为什么不跑在 `GWEI_TEST_DATABASE_URL` 指向的库上:那个库被别的用例用
    `create_all` 建过裸表,表在、策略不在,测出来的"没拦住"是假的。这里从
    `template0` 旁开一个新库,迁移里写的策略、视图与角色一次到位,也不污染别的用例。
    """
    import uuid

    import sqlalchemy as sa

    # 连一个与测试库同编码的管理库:`postgres` 库在有些安装里是 SQL_ASCII,
    # 连上去连版本串都会读成 bytes
    admin_url = sa.engine.make_url(url).set(database="gwei_admin")
    name = f"gwei_rls_{uuid.uuid4().hex[:8]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            # 新库照抄测试库自己的编码,而不是 template0 的:两者不一致时
            # 连接协议会把版本串读成 bytes,报一个与测试意图毫无关系的 TypeError
            conn.execute(
                sa.text(
                    f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'UTF8\' '
                    "LC_COLLATE 'C' LC_CTYPE 'C'"
                )
            )
    finally:
        admin.dispose()

    fresh = str(sa.engine.make_url(url).set(database=name))
    from alembic import command
    from alembic.config import Config

    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "engine" / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "engine" / "migrations"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = fresh
    # alembic 的 env.py 会调 `logging.fileConfig(alembic.ini)`,而那份配置默认
    # `disable_existing_loggers=True`:跑完迁移,别的用例的 caplog 就再也抓不到
    # `engine.*` 的日志了。这里只关心 DDL,不需要它重配日志——把 `fileConfig`
    # 在本次调用期间换成空操作,跑完还原。
    import logging.config

    real_file_config = logging.config.fileConfig
    logging.config.fileConfig = lambda *a, **k: None
    try:
        # 迁移链现在自带控制台那两张表(012),干净库可以直接跑到头
        command.upgrade(cfg, "head")
    finally:
        logging.config.fileConfig = real_file_config
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return fresh


def _drop_database(url: str, fresh: str) -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(fresh)
    engine.dispose()
    name = sa.engine.make_url(fresh).database
    admin = sa.create_engine(
        sa.engine.make_url(url).set(database="gwei_admin"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        admin.dispose()


@requires_postgres
def test_the_policy_hides_other_tenants_rows():
    """写两条不同租户的行,带租户读只能看见自己那条;不带租户读是空集。

    这两条判据合起来才是「忘了写 where 的后果是空集,不是别人的账」。
    """
    import sqlalchemy as sa
    import uuid

    url = os.environ["GWEI_TEST_DATABASE_URL"]
    fresh = _ensure_schema(url)
    engine = sa.create_engine(fresh)
    run = uuid.uuid4().hex[:8]
    unit_a, unit_b = f"a-{run}", f"b-{run}"

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO change_events (unit_id, tenant, binding, verdict, "
                "idempotency_key, created_at, payload) VALUES "
                "(:u, :t, 'local', 'kept', :k, '2026-01-01T00:00:00Z', '{}')"
            ),
            [
                {"u": unit_a, "t": f"acme-{run}", "k": f"k-{run}-a"},
                {"u": unit_b, "t": f"other-{run}", "k": f"k-{run}-b"},
            ],
        )

    def visible(tenant: str | None, unit: str) -> int:
        """以插件角色查一次:受限角色 + 本租户,两个条件同时成立才看得见。

        超级用户与 `BYPASSRLS` 角色会绕过策略(连 `FORCE` 也拦不住),
        部署里应用账号往往就是这样,所以这里显式换到插件角色——
        它就是"第三方插件读库"时的身份。
        """
        with engine.connect() as conn:
            conn.execute(sa.text("SET ROLE gwei_plugin_reader"))
            if tenant is not None:
                conn.execute(
                    sa.text("SELECT set_config('gwei.tenant', :t, true)"), {"t": tenant}
                )
            out = conn.execute(
                sa.text("SELECT count(*) FROM v_plugin_changes WHERE unit_id = :u"),
                {"u": unit},
            ).scalar_one()
            conn.rollback()
            return out

    try:
        assert visible(f"acme-{run}", unit_a) == 1
        assert visible(f"acme-{run}", unit_b) == 0
        # 不设租户:什么都不返回(默认拒绝,不是默认放行)
        assert visible(None, unit_a) == 0
    finally:
        with engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM change_events WHERE unit_id IN (:a, :b)"),
                {"a": unit_a, "b": unit_b},
            )
        engine.dispose()
        _drop_database(url, fresh)


@requires_postgres
def test_the_plugin_role_cannot_write_and_sees_only_its_tenant():
    """受限角色:只读、只看得见本租户。写被拒由权限层挡,不是靠自觉。"""
    import sqlalchemy as sa
    import uuid

    url = os.environ["GWEI_TEST_DATABASE_URL"]
    fresh = _ensure_schema(url)
    engine = sa.create_engine(fresh)
    run = uuid.uuid4().hex[:8]
    unit = f"r-{run}"

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO change_events (unit_id, tenant, binding, verdict, "
                "idempotency_key, created_at, payload) VALUES "
                "(:u, :t, 'local', 'kept', :k, '2026-01-01T00:00:00Z', '{}')"
            ),
            {"u": unit, "t": f"acme-{run}", "k": f"k-{run}"},
        )

    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SET ROLE gwei_plugin_reader"))
            conn.execute(
                sa.text("SELECT set_config('gwei.tenant', :t, true)"), {"t": f"acme-{run}"}
            )
            seen = conn.execute(
                sa.text("SELECT count(*) FROM v_plugin_changes WHERE unit_id = :u"),
                {"u": unit},
            ).scalar_one()
            assert seen == 1
            conn.rollback()
        # 写:权限层直接拒
        with engine.connect() as conn:
            conn.execute(sa.text("SET ROLE gwei_plugin_reader"))
            with pytest.raises(sa.exc.ProgrammingError):
                conn.execute(
                    sa.text(
                        "INSERT INTO change_events (unit_id, tenant, binding, verdict, "
                        "idempotency_key, created_at, payload) VALUES "
                        "('x', 'acme', 'local', 'kept', 'kx', 'n', '{}')"
                    )
                )
            conn.rollback()
    finally:
        with engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM change_events WHERE unit_id = :u"), {"u": unit}
            )
        engine.dispose()
        _drop_database(url, fresh)
