# engine/api/app.py
"""FastAPI 应用入口 - 既未 · Gwei。"""

import logging
from contextlib import asynccontextmanager

from dbos import DBOS, DBOSConfig
from fastapi import FastAPI

from engine.api.auth import load_tokens, make_middleware, set_auth_required
from engine.api.routes.auth import router as auth_router
from engine.api.routes.registration import router as registration_router
from engine.api.routes.health import router as health_router
from engine.api.routes.plugins import router as plugins_router
from engine.api.routes.quota import router as quota_router
from engine.api.routes.agent import router as agent_router
from engine.api.routes.changes import router as changes_router
from engine.api.routes.incidents import router as incidents_router
from engine.api.routes.issues import router as issues_router
from engine.api.routes.mcp import router as mcp_router
from engine.api.routes.api_keys import router as api_keys_router
from engine.api.routes.console import router as console_router
from engine.api.routes.console_agent import router as console_agent_router
from engine.api.routes.rbac import router as rbac_router
from engine.api.routes.release_settings import router as release_settings_router
from engine.api.routes.settings_scopes import router as settings_scopes_router
from engine.api.routes.invitations import router as invitations_router
from engine.api.routes.project_settings import router as project_settings_router
from engine.api.routes.repos import router as repos_router
from engine.api.routes.webhook import router as webhook_router
from engine.plugin_manager import registry
from engine.shared.config import config
import engine.workflows.pipeline as pipeline  # noqa: F401 — 导入即注册 DBOS 工作流/步骤
from engine.shared.system_scopes import register_system_scopes

# 系统域 scope(注册策略、核验通道、OIDC、配额):注册策略与配额的读取方按
# scope 取值,先注册它们再进 lifespan,库里那份覆盖才读得到
register_system_scopes()

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
    # 顺序有讲究:库里的配置必须先装好,插件 on_startup 才读得到自己的凭据
    from engine.harness import build_env  # noqa: F401 — 导入即注册 harness-env scope
    from engine.shared.settings_store import create_settings_store, ensure_schema as ensure_settings_schema

    # 隔离这件事先问一遍:清单里的表在库里都得有策略。saas 档缺一张就不启动 ——
    # 一个不知道隔离有没有生效的共享部署,比一个起不来的部署更贵。
    from engine.db.engine import enforce_isolation

    try:
        await enforce_isolation()
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - 库还没起来/还没迁移:交给下面的迁移去说
        logger.warning("隔离策略这一遍没查成", exc_info=True)

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

    # 项目这一级的值(可见性 / 默认发布参数 / 凭据索引):发布解析是同步的,
    # 它读的是这里装进去的那份快照。库仍然是权威 —— 接口写完会再刷一次。
    try:
        from engine.projects import reload_project_snapshot

        await reload_project_snapshot()
    except Exception:  # noqa: BLE001 - 表还没建好时按"没有项目"处理
        logger.warning("读不到项目级的值,这次按工作区默认", exc_info=True)

    # Startup: 先装回启停决定,再发现与启动(顺序反了决定会在重启后被绕过)。
    # 两层各装各的:部署级决定装进 `_decisions`,租户级装进 `_tenancy`;
    # 真的在跑 = 平台提供了 且 这个租户没关掉它。
    from engine.plugin_manager import enablement, tenancy

    registry.set_decisions(await enablement.load_decisions())
    try:
        from engine.shared.settings_store import create_settings_store

        stored = await create_settings_store().load()
    except Exception:  # noqa: BLE001 - 读不到就当作没有租户决定
        logger.warning("读不到租户级插件启停决定,这次按平台默认", exc_info=True)
        stored = {}
    tenants = {tenant for tenant in stored if tenant} or {
        config.settings.default_tenant_slug
    }
    registry.set_tenancy(
        {tenant: await tenancy.load_tenancy(tenant) for tenant in sorted(tenants)}
    )

    registry.discover()

    # 进程外插件(PLUGINS_GRPC)也走同一条注册路径,只是实例换成一个远程代理
    from engine.plugin_manager.grpc_loader import register_grpc_plugins

    try:
        registered = register_grpc_plugins()
    except Exception:  # noqa: BLE001 - 接不上只告警
        logger.warning("gRPC 插件没装上", exc_info=True)
    else:
        if registered:
            logger.info("gRPC plugins registered: %d", registered)

    # 全部实例就位之后统一 on_startup:进程内与进程外一视同仁
    await registry.launch()

    # 插件自己声明的配置有缺项就点名
    for scope in config.list_scopes():
        missing = config.validate_scope(scope.name, config.settings.default_tenant_slug)
        if missing:
            logger.warning("插件配置缺项 %s: %s", scope.name, ", ".join(missing))

    # 鉴权:配了机器令牌或者库里已经有人,就要求身份。首启初始化之后由
    # /api/auth/setup 当场翻转,不用重启。所以"要不要鉴权"只能在这里判定并在
    # 这里说一次——在 import 时按 api_tokens 是否为空去说,会把已有用户的实例
    # 说成"不鉴权"。
    from engine.auth import store as auth_store

    try:
        has_users = await auth_store.persons_exist()
    except Exception:  # noqa: BLE001 - 表还没建好时按"没有用户"处理,setup 会再处理
        logger.warning("读不到用户表,鉴权先按令牌配置决定", exc_info=True)
        has_users = False
    # 密钥是凭据,不是鉴权开关;要不要认身份仍由令牌与用户决定
    if config.settings.change_ledger_backend != "file":
        from engine.auth import keys as key_store

        await key_store.ensure_schema()
    auth_on = bool(API_TOKENS) or has_users
    set_auth_required(auth_on)
    if auth_on:
        reasons = []
        if API_TOKENS:
            reasons.append(f"{len(API_TOKENS)} 条控制台令牌")
        if has_users:
            reasons.append("库里已有用户")
        logger.info("控制台鉴权已开启:%s", "、".join(reasons))
    else:
        logger.warning(
            "控制台鉴权已关闭:没有控制台令牌,库里也没有用户;"
            "by 与 tenant 采信调用方自报。单机自用可以,对外必须配"
        )

    # Startup: 账本表(仓库没有迁移工具,checkfirst 建一次)
    if config.settings.change_ledger_backend != "file":
        from engine.db.change_ledger import ensure_schema

        await ensure_schema()
        from engine.plugin_manager.tenancy import ensure_schema as ensure_tenancy_schema

        await ensure_tenancy_schema()
        from engine.agent.console import ensure_schema as ensure_console_schema
        from engine.incidents import ensure_schema as ensure_incident_schema

        await ensure_incident_schema()
        await ensure_console_schema()
        logger.info("Change ledger + incidents + console sessions ready (backend=db)")

    # Startup: 启动 DBOS 并注册工作流队列(按租户分区,公平性执行点)
    logger.info("Launching DBOS...")
    DBOS.launch()
    await DBOS.register_queue_async(pipeline.WORKFLOW_QUEUE, partition_concurrency=4)
    logger.info("DBOS launched (partitioned queue: %s)", pipeline.WORKFLOW_QUEUE)

    # Startup: 周期巡检。清单里声明的 schedule 在这里装进 DBOS 的调度器,
    # 同一周期只跑一次由系统库里的工作流 id 保证,重启后不会重跑。
    # 装不上只点名,不因此起不来
    from engine.scheduler import apply_registry_schedules

    try:
        outcome = apply_registry_schedules(
            registry, tenant=config.settings.default_tenant_slug
        )
    except Exception:  # noqa: BLE001 - 起不来只告警
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
app.include_router(registration_router)
app.include_router(plugins_router)
app.include_router(quota_router)
app.include_router(console_router)
app.include_router(repos_router)
app.include_router(changes_router)
app.include_router(agent_router)
app.include_router(incidents_router)
app.include_router(issues_router)
app.include_router(settings_scopes_router)
app.include_router(release_settings_router)
app.include_router(rbac_router)
app.include_router(invitations_router)
app.include_router(project_settings_router)
app.include_router(webhook_router)
app.include_router(mcp_router)
app.include_router(api_keys_router)
app.include_router(console_agent_router)

# 令牌在 import 时就得读出来(中间件要它算 X-Gwei-Auth),但"要不要鉴权"由
# 启动末尾的 lifespan 判定:那时才知道库里有没有用户。判定本身只在一处发声。
API_TOKENS = load_tokens(config.settings.api_tokens)
app.middleware("http")(make_middleware(API_TOKENS))