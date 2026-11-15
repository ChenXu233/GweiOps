# tests/conftest.py
"""全局测试配置。

门控约定:GWEI_TEST_DATABASE_URL 指向测试用 Postgres 时,同步把 DATABASE_URL
(业务库,engine.db 于导入期创建 async 引擎)指向同一实例——console/dashboard
等走 async_session_factory 的接口因此与门控端点共用同一库。必须在任何
engine.* 导入前设置,conftest 先于测试模块加载,顺序天然满足。
"""

import os

import pytest
import sqlalchemy.engine

GATED = os.environ.get("GWEI_TEST_DATABASE_URL")

if GATED and not os.environ.get("DATABASE_URL"):
    url = sqlalchemy.engine.make_url(GATED)
    # GATE 变量使用 psycopg 驱动(DBOS);业务引擎用 asyncpg
    url = url.set(drivername="postgresql+asyncpg")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)


@pytest.fixture(autouse=True)
def _allow_every_capability(monkeypatch):
    """测试默认把全部能力当成自动收敛。

    生产缺省是"空 = 一律等人",那样每个用例都得先声明一次自己的能力,测的就
    不是它本来要测的东西了。判定走的是同一条代码路径,只是名单不同;
    缺省口径本身在 test_change_policy 里有专门的用例。
    """
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "autonomous_capabilities", "*")


@pytest.fixture(autouse=True)
def _reset_plugin_registry():
    """每个测试后清空生产 registry 单例。

    部分测试会 discover 真实 builtin 插件;不清空会泄漏到后续测试,
    使能力通道(capability)命中真实实例而非测试替身。
    """
    yield
    try:
        from engine.plugin_manager import registry

        registry._reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_release_settings_rows():
    """每个测试前后清掉 config 内存覆盖里的发布配置行。

    release 的三层解析读的是 config 单例的内存覆盖;测试写进去的
    (tenant, "release", key) 行不清掉会泄漏到后续测试。
    """
    from engine.shared.config import config

    def _drop_release_rows():
        stored = config.all_stored()
        for tenant in list(stored):
            stored[tenant].pop("release", None)
            if not stored[tenant]:
                stored.pop(tenant)
        config.apply_stored(stored)

    _drop_release_rows()
    yield
    _drop_release_rows()


@pytest.fixture(autouse=True)
def _dispose_async_engine():
    """每个测试后释放全局 async 引擎连接池。

    engine.db 的池在导入期创建,绑定首个使用它的事件循环;pytest-asyncio
    为每个异步测试新建循环,复用旧池会报 "another operation is in progress"。
    dispose 后下次使用会按当前循环重建,代价是每测试一次重连(测试规模下可忽略)。
    """
    yield
    try:
        import asyncio

        from engine.db import engine as global_engine

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(global_engine.dispose())
        finally:
            loop.close()
    except Exception:
        pass
