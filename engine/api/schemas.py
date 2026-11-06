# engine/api/schemas.py
"""控制台 API 的响应契约。

这里是 **唯一** 的接口形状定义:
- FastAPI 用它们生成 OpenAPI(/openapi.json);
- 前端用生成的 openapi.json 生成 TypeScript 类型与调用点;
- 两边都不再手抄字段名。
改这里的字段等于改接口,必须同步跑 `python scripts/dump_openapi.py`,
否则前端的 `pnpm gen:api` 拿到的是旧形状。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["critical", "medium", "low"]
IssueStatus = Literal["pending_review", "canary", "approved", "completed", "rolled_back"]
TimelineStatus = Literal["done", "active", "pending"]
Verdict = Literal["pending", "kept", "rolled_back", "blocked", "vetoed", "irreversible"]


class HealthDTO(BaseModel):
    status: str
    version: str


# ---------------------------------------------------------------------------
# 控制室
# ---------------------------------------------------------------------------


class PatchDTO(BaseModel):
    id: str
    # 类型与风险来自插件写入的自由文本,不收敛成枚举:收窄会让没见过的值直接 500
    type: str
    risk: str
    lines: int
    passRate: float
    latency: str
    description: str


class TimelineStepDTO(BaseModel):
    id: str
    label: str
    status: TimelineStatus


class CanaryMetricsDTO(BaseModel):
    # 有默认值:金丝雀链路未接线时这里是 0,不是编出来的观测值
    passRate: float = 0
    errorRate: float = 0
    p99Latency: str = ""
    memoryPeak: str = ""


class CanaryProgressDTO(BaseModel):
    """金丝雀进度。引擎目前不产出,DTO 里显式留空,前端按"没进入灰度"渲染。"""

    current: str = ""
    steps: list[str] = []
    completedSteps: list[str] = []
    metrics: CanaryMetricsDTO = CanaryMetricsDTO()


class IssueDTO(BaseModel):
    id: str
    title: str
    source: str
    severity: Severity
    status: IssueStatus
    repo: str
    triggeredAt: str
    patches: list[PatchDTO]
    timeline: list[TimelineStepDTO]
    canary: CanaryProgressDTO | None = None


class DashboardDTO(BaseModel):
    status: str
    consecutiveDays: int
    lastIncident: str
    pendingReview: int
    overnightFixed: int
    memoryEntries: int
    mttr: float
    successRate: float
    activeAgents: int
    healthHistory: list[bool]


class PendingIssueDTO(BaseModel):
    id: str
    title: str
    severity: Severity
    patchCount: int
    status: IssueStatus


class OvernightEventDTO(BaseModel):
    time: str
    title: str
    description: str
    result: Literal["success", "failed"]


class CanaryStatusDTO(BaseModel):
    issueId: str
    issueTitle: str
    currentStep: str
    steps: list[str]
    metrics: CanaryMetricsDTO


# ---------------------------------------------------------------------------
# 仓库 / 设置 / 执行记录
# ---------------------------------------------------------------------------


class RepoDTO(BaseModel):
    id: str
    name: str
    icon: str
    status: str
    issueCount: int
    activeAgents: int
    lastSyncAt: str


class SettingsDTO(BaseModel):
    teamName: str
    memberCount: int
    adminCount: int
    plan: str
    planPrice: str
    issueQuota: str
    notificationChannels: list[str]
    ssoProvider: str


class RunRowDTO(BaseModel):
    id: str
    issueId: str
    issueTitle: str
    issueNumber: int
    repo: str
    status: str
    source: str
    startedAt: str | None = None
    endedAt: str | None = None
    durationMs: int | None = None
    state: dict[str, Any] = {}


class RunListDTO(BaseModel):
    items: list[RunRowDTO]
    total: int


# ---------------------------------------------------------------------------
# 指标 / 插件
# ---------------------------------------------------------------------------


class MetricDTO(BaseModel):
    name: str
    labels: dict[str, str] = {}
    value: float


class PluginPageDTO(BaseModel):
    title: str = ""
    entry: str = ""


class PluginWidgetMetricDTO(BaseModel):
    """插件声明的指标条目。插件可以带额外键,一律放过。"""

    model_config = ConfigDict(extra="allow")

    label: str = ""
    value: str | int | float = ""
    sub: str | None = None
    variant: str | None = None


class PluginWidgetItemDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str = ""


class PluginWidgetDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    slot: str
    kind: str
    span: int
    title: str
    metrics: list[PluginWidgetMetricDTO] = []
    items: list[PluginWidgetItemDTO] = []
    plugin: str | None = None


class PluginDTO(BaseModel):
    name: str
    version: str
    type: str
    description: str
    capabilities: list[str] = []
    widgets: list[PluginWidgetDTO] = []
    pages: list[PluginPageDTO] = []


# ---------------------------------------------------------------------------
# 变更账本
# ---------------------------------------------------------------------------


class ChangeEffectDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    task: str = ""
    args: dict[str, Any] = {}
    undo_task: str = ""
    undo_kind: str = ""
    label: str = ""
    capability: str = ""


class ChangeIntentDTO(BaseModel):
    """意图。引擎只保证 summary 在,其余键由提供者自己加。"""

    model_config = ConfigDict(extra="allow")

    summary: str = ""


class ChangeRowDTO(BaseModel):
    """账本一行。字段与 ChangeUnit.to_dict() 对齐,缺省值兜住旧行。"""

    model_config = ConfigDict(extra="allow")

    id: str
    created_at: str = ""
    verdict: Verdict = "pending"
    reason: str = ""
    binding: str = ""
    tenant: str = ""
    incident_id: str = ""  # 同一次事故的变更共用它;空 = 不属于任何一次
    handle: str | None = None
    idempotency_key: str = ""
    intent: ChangeIntentDTO = ChangeIntentDTO()
    effect: ChangeEffectDTO = ChangeEffectDTO()
    facts: dict[str, Any] = {}
    window: dict[str, Any] | None = None
    # 以这一行为当前状态时,还撤不撤得回来。历史行按它自己那一刻算。
    undoable: bool = False
    undo_reason: str = ""
    undo_expires_at: str = ""  # 空字符串 = 不会过期(对称撤销)


class ChangeListDTO(BaseModel):
    items: list[ChangeRowDTO]
    total: int


class ChangeDetailDTO(BaseModel):
    latest: ChangeRowDTO
    history: list[ChangeRowDTO]


# ---------------------------------------------------------------------------
# 事故
# ---------------------------------------------------------------------------


class IncidentDTO(BaseModel):
    """一次事故。status 停在 open 说明那一场开了没收口。"""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant: str = ""
    signal_source: str = ""
    signal_title: str = ""
    status: Literal["open", "closed"] = "open"
    source: str = ""
    started_at: str = ""
    finished_at: str = ""
    summary: str = ""
    counts: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    exhausted: bool = False


class IncidentListDTO(BaseModel):
    items: list[IncidentDTO]
    total: int