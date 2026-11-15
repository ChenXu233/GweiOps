# engine/api/app.py
"""FastAPI 应用入口 - 既未 · Gwei。"""

import logging
from contextlib import asynccontextmanager

from dbos import DBOS, DBOSConfig
from fastapi import FastAPI

from engine.api.auth import load_tokens, make_middleware, set_auth_required
from engine.api.routes.auth import router as auth_router
from engine.api.routes.health import router as health_router
from engine.api.routes.plugins import router as plugins_router
from engine.api.routes.agent import router as agent_router
from engine.api.routes.changes import router as changes_router
from engine.api.routes.incidents import router as incidents_router
from engine.api.routes.issues import router as issues_router
from engine.api.routes.mcp import router as mcp_router
from engine.api.routes.mcp import router as mcp_router
from engine.api.routes.console import router as console_router
from engine.api.routes.rbac import router as rbac_router
from engine.api.routes.settings_scopes import router as settings_scopes_router
from engine.api.routes.webhook import router as webhook_router
from engine.plugin_manager import registry
from engine.shared.config import config
import engine.workflows.pipeline as pipeline  # noqa: F401 — 导入即注册 DBOS 工作流/步骤

logger = logging.getLogger(__name__)

# DBOS 持久化执行：系统表位于同一 Postgres 实例的独立 dbos schema，
# URL 归一为同步驱动（DBOS 内部使用 psycopg）。
dbos = DBOS(
    config=DBOSConfig(
        name=config.settings.app_name,
        system_database_url=config.settings.database_url.replace("+asyncpg", ""),
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - startup 初始化插件注册表与 DBOS,shutdown 逆序关闭。"""
    # 顺序有讲究:库里的配置必须先装好,插件 on_startup 才读得到自己的凭据。
    # 反过来(先 launch 再装配置)是一个真 bug:插件看到的是空配置,启动失败被隔离,
    # 之后页面上填的值永远不生效,而失败只留一行日志。
    from engine.harness import build_env  # noqa: F401 — 导入即注册 harness-env scope
    from engine.shared.settings_store import create_settings_store, ensure_schema as ensure_settings_schema

    if config.settings.change_ledger_backend != "file":
        try:
            await ensure_settings_schema()
        except Exception:  # noqa: BLE001 - 建不出来就退回环境变量,不因此起不来
            logger.warning("建不出配置表,这次只用环境变量", exc_info=True)

    # 存进库里的配置值:启动时装一次,之后写入时原地更新(所以取值仍然是同步的)
    try:
        config.apply_stored(await create_settings_store().load())
        logger.info("Stored settings loaded: %d scope(s)", len(config.all_stored()))
    except Exception:  # noqa: BLE001 - 读不到就只用环境变量,不因此起不来
        logger.warning("读不到存储的配置,这次只用环境变量", exc_info=True)

    # Startup: 先装回"人在控制台上点过的启停决定",再发现与启动。
    # 顺序反了就是一个真 bug:控制台上关掉的插件会在重启后照常跑回来,而没人记得为什么。
    from engine.plugin_manager import enablement

    registry.set_decisions(await enablement.load_decisions())

    # 发现 ≠ 启用:发现记录全部清单,决定为启用的才导入、注册、进索引
    registry.discover()

    # 进程外插件(PLUGINS_GRPC)也走同一条注册路径,只是实例换成一个远程代理:
    # 声明仍在清单里(见 grpc_loader),能力解析与进程内插件没有区别。
    # 远端连不上只影响它自己,不该拦住本机这一批已经能用的插件。
    from engine.plugin_manager.grpc_loader import register_grpc_plugins

    try:
        registered = register_grpc_plugins()
    except Exception:  # noqa: BLE001 - 远端插件接不上不等于平台起不来
        logger.warning("gRPC 插件没装上", exc_info=True)
    else:
        if registered:
            logger.info("gRPC plugins registered: %d", registered)

    # 全部实例就位之后统一 on_startup:进程内与进程外一视同仁
    await registry.launch()

    # 插件自己声明的配置有缺项就说出来:声明了却没人填,比没声明更糟——
    # 那种沉默会在第一次真要调下游的时候才爆。
    for scope in config.list_scopes():
        missing = config.validate_scope(scope.name, config.settings.default_tenant_slug)
        if missing:
            logger.warning("插件配置缺项 %s: %s", scope.name, ", ".join(missing))

    # 鉴权:配了机器令牌或者库里已经有人,就要求身份。首启初始化之后由
    # /api/auth/setup 自己把它翻过来,不用重启。
    from engine.auth import store as auth_store

    try:
        has_users = await auth_store.users_exist()
    except Exception:  # noqa: BLE001 - 表还没建好时按"没有用户"处理,setup 会再处理
        logger.warning("读不到用户表,鉴权先按令牌配置决定", exc_info=True)
        has_users = False
    set_auth_required(bool(API_TOKENS) or has_users)

    # Startup: 账本表(仓库没有迁移工具,checkfirst 建一次)
    if config.settings.change_ledger_backend != "file":
        from engine.db.change_ledger import ensure_schema

        await ensure_schema()
        from engine.incidents import ensure_schema as ensure_incident_schema

        await ensure_incident_schema()
        logger.info("Change ledger + incidents ready (backend=db)")

    # Startup: 启动 DBOS 并注册工作流队列(按租户分区,公平性执行点)
    logger.info("Launching DBOS...")
    DBOS.launch()
    await DBOS.register_queue_async(pipeline.WORKFLOW_QUEUE, partition_concurrency=4)
    logger.info("DBOS launched (partitioned queue: %s)", pipeline.WORKFLOW_QUEUE)

    # Startup: 周期巡检。清单里声明的 schedule 在这里装进 DBOS 的调度器,
    # 同一周期只跑一次由系统库里的工作流 id 保证,重启后不会重跑。
    # 装不上只点名,不因此起不来:一个写坏的周期不该让整个引擎停摆。
    from engine.scheduler import apply_registry_schedules

    try:
        outcome = apply_registry_schedules(
            registry, tenant=config.settings.default_tenant_slug
        )
    except Exception:  # noqa: BLE001 - 调度器起不来不等于平台起不来
        logger.warning("周期巡检没有装上", exc_info=True)
    else:
        if outcome["applied"]:
            logger.info("Scheduled scans: %s", ", ".join(outcome["applied"]))
        if outcome["failed"]:
            logger.warning(
                "巡检周期装不上: %s",
                "; ".join(f"{f['schedule']}({f['error']})" for f in outcome["failed"]),
            )
        if outcome["removed"]:
            logger.info("Removed stale schedules: %s", ", ".join(outcome["removed"]))

    yield

    # Shutdown: 先停工作流执行器,再停插件
    logger.info("Shutting down DBOS...")
    dbos.destroy()

    logger.info("Shutting down plugins...")
    await registry.shutdown()


app = FastAPI(
    title="既未 · Gwei",
    description="AI 驱动的 GitHub Issue 修复平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(plugins_router)
app.include_router(console_router)
app.include_router(changes_router)
app.include_router(agent_router)
app.include_router(incidents_router)
app.include_router(issues_router)
app.include_router(settings_scopes_router)
app.include_router(rbac_router)
app.include_router(webhook_router)
app.include_router(mcp_router)

# 控制台鉴权:没有配置令牌就不鉴权,但要说出来——静默降级的安全开关不叫开关。
API_TOKENS = load_tokens(config.settings.api_tokens)
if API_TOKENS:
    logger.info("Console auth enabled: %d token(s)", len(API_TOKENS))
else:
    logger.warning(
        "API 未配置控制台令牌(api_tokens 为空):服务不鉴权,by 与 tenant 由调用方自报"
    )
app.middleware("http")(make_middleware(API_TOKENS))