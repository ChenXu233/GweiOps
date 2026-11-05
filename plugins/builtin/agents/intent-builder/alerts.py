# plugins/builtin/agents/intent-builder/alerts.py
"""监控告警 → intent 的参考翻译。

平台不猜动作。告警规则可以用 `annotations.gwei_effect` 声明一个动作(JSON),
这个提供者只负责把它翻译成 intent —— 运维知识留在运维写规则的地方。

例:

    annotations:
      summary: 内存占用过高
      gwei_effect: '{"capability": "compose.scale",
                     "args": {"project_dir": "/srv/api", "service": "api", "replicas": 10}}'

没有声明就返回空 effects。空不丢人,编一个才丢人。
"""

from __future__ import annotations

import json
from typing import Any


def declared_effect(signal: dict[str, Any]) -> dict[str, Any] | None:
    """读出告警里声明的动作。没声明、不是对象、解析不了,一律当作没声明。"""
    annotations = signal.get("annotations") or {}
    if not isinstance(annotations, dict):
        return None

    raw = annotations.get("gwei_effect")
    if isinstance(raw, dict):
        payload: Any = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        return None

    if not isinstance(payload, dict):
        return None

    capability = payload.get("capability")
    if not isinstance(capability, str) or not capability.strip():
        return None

    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return None

    return {"capability": capability.strip(), "args": dict(args)}


def intent_from_alert(signal: dict[str, Any]) -> dict[str, Any]:
    """把一条告警翻成 intent。动作只能来自告警自己的声明。"""
    subject = str(signal.get("subject") or signal.get("title") or "")
    evidence = [
        {"kind": "alertmanager", "ref": str(signal.get("ref") or signal.get("title") or "")}
    ]
    alertname = (signal.get("labels") or {}).get("alertname")
    if alertname:
        evidence.append({"kind": "alert", "ref": str(alertname)})

    effect = declared_effect(signal)
    if effect is None:
        return {
            "summary": f"告警「{signal.get('title', '')}」没有声明动作",
            "evidence": evidence,
            "effects": [],
            "rationale": "告警规则里没有 gwei_effect;平台不替它决定该做什么。",
        }

    return {
        "summary": f"针对 {subject} 执行 {effect['capability']}",
        "evidence": evidence,
        "effects": [effect],
        "rationale": "执行告警规则声明的动作;可逆性与窗口由该能力的声明决定,不由告警决定。",
    }
