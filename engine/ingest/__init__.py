# engine/ingest/__init__.py
"""信号入口:把各家的载荷翻译成同一种信号。"""

from .alertmanager import from_alert, parse_alerts
from .signal import SOURCES, SEVERITIES, SignalError, from_github, normalize

__all__ = [
    "SOURCES",
    "SEVERITIES",
    "SignalError",
    "normalize",
    "from_github",
    "from_alert",
    "parse_alerts",
]
