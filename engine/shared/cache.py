# engine/shared/cache.py
"""Redis 增益层 — 投递去重与结果缓存。

设计约束：Redis 只承载可丢失的临时状态（工作流持久化一律在 Postgres/DBOS），
所有操作 best-effort —— Redis 不可用时降级放行并记录日志，绝不阻塞主链路。
"""

import hashlib
import json
import logging
from typing import Any, Awaitable, Callable

import redis.asyncio as aredis

from engine.shared.config import config

logger = logging.getLogger(__name__)

WEBHOOK_DEDUP_TTL_S = 6 * 3600  # GitHub 重投递窗口
LLM_ANALYSIS_TTL_S = 24 * 3600  # Issue 内容未变时复用感知分析结果

_client: aredis.Redis | None = None


def _get_client() -> aredis.Redis:
    global _client
    if _client is None:
        _client = aredis.from_url(config.settings.redis_url, decode_responses=True)
    return _client


def cache_key(*parts: str) -> str:
    """由若干字段生成稳定缓存键（内容哈希，避免超长键与特殊字符）。"""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"gwei:{digest}"


async def dedup_once(key: str, ttl_s: int) -> bool:
    """SET NX EX 去重：返回 True 表示首次出现，False 表示重复。

    Redis 故障时返回 True（放行），由 DBOS SetWorkflowID 兜底幂等。
    """
    try:
        return bool(await _get_client().set(key, "1", nx=True, ex=ttl_s))
    except Exception as e:
        logger.warning("Redis dedup failed, degrading to pass-through: %s", e)
        return True


async def cached_json(key: str, ttl_s: int, factory: Callable[[], Awaitable[Any]]) -> Any:
    """读缓存 → 未命中则执行 factory 并回写。Redis 故障时等价于直连 factory。"""
    client: aredis.Redis | None
    try:
        client = _get_client()
        raw = await client.get(key)
        if raw is not None:
            return json.loads(raw)
    except Exception as e:
        logger.warning("Redis cache read failed: %s", e)
        client = None

    value = await factory()

    if client is not None:
        try:
            await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_s)
        except Exception as e:
            logger.warning("Redis cache write failed: %s", e)
    return value
