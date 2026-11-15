# engine/ingest/__init__.py
"""信号入口:把各家的载荷翻译成同一种信号。

各家载荷的翻译不在核心里:GitHub 在适配器里,告警系统在各自的适配器插件里
(例如 `plugins/builtin/adapters/alertmanager`)。核心只保留信号这一种说法。
"""

from .signal import SEVERITIES, SignalError, from_github, normalize

__all__ = [
    "SEVERITIES",
    "SignalError",
    "normalize",
    "from_github",
]
