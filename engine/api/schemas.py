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

from pydantic import BaseModel, ConfigDict, Field

# failed = 确定没动(可重试);unknown = 不知道动没动(要人核);irreversible = 确实动了且撤不回来。
Verdict = Literal[
    "pending", "kept", "rolled_back", "blocked", "vetoed", "failed", "unknown", "irreversible"
]


class HealthDTO(BaseModel):
    status: str
    version: str


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
    """一个被发现过的插件。**发现 ≠ 启用**:`enabled` 才是它此刻在不在流程里。

    只列已加载实例的话,未启用的插件在页面上根本不存在,人就没法把它打开——
    所以这里按"发现的清单"枚举,`enabled` 与 `instances` 说清它此刻的状态。
    """

    name: str
    version: str
    type: str
    description: str
    capabilities: list[str] = []
    widgets: list[PluginWidgetDTO] = []
    pages: list[PluginPageDTO] = []
    # 此刻能不能被解析到。false 时下面的 capabilities 只是声明,不是可用能力。
    enabled: bool = False
    # 活着的实例键。同一清单按租户/目标挂多实例时这里会有多个。
    instances: list[str] = []
    # 为什么是这个状态(在 PLUGINS_ENABLED 里 / 清单 default_enabled: false / 运行期停用)
    reason: str = ""
    # 注册成功但起不来时的原因(如密钥没配)。空 = 没有已知的启动失败。
    # "已启用"与"能用"是两件事,两者对不上时页面得说得出为什么。
    error: str = ""


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
    # 这一轮改了哪些文件,以及本打算做什么(一个候选都没落下时,只有它说得清经过)。
    diff: list[dict[str, Any]] = []
    intent: dict[str, Any] = {}
    exhausted: bool = False


class IncidentListDTO(BaseModel):
    items: list[IncidentDTO]
    total: int


# ---------------------------------------------------------------------------
# 议题时间线
# ---------------------------------------------------------------------------

# 用户只看到这三个。七种结论仍原样待在的账本里,列表上不出现原词。
IssueState = Literal["waiting", "running", "landed"]
# 一段一件事:哪来的信号、看到了什么、打算做什么、动了什么、验证、结论。
TimelineSegmentKind = Literal[
    "signal", "diagnosis", "intent", "change", "verify", "conclusion"
]


class TimelineEvidenceDTO(BaseModel):
    """证据:存下来的原文。前端不加工,截断了要标出来。"""

    label: str = ""
    kind: str = "json"  # json | text | url
    content: Any = None
    truncated: bool = False


class TimelineSegmentDTO(BaseModel):
    """时间线上的一段。summary 是一句人话,detail 是工程决策要点,evidence 是原文。"""

    model_config = ConfigDict(extra="allow")

    id: str
    kind: TimelineSegmentKind
    at: str = ""
    summary: str = ""
    detail: dict[str, Any] = {}
    evidence: list[TimelineEvidenceDTO] = []


class TimelineBranchDTO(BaseModel):
    """话题上此刻开着的那个 PR。没有就是没有,不编一条分支出来。"""

    repo: str = ""
    head: str = ""
    pull: str = ""
    url: str = ""


class RoundDiffDTO(BaseModel):
    """一轮里一个文件的改动。行数是平台从工作区数的,不是 agent 自报的。"""

    path: str
    added: int = 0
    removed: int = 0
    status: Literal["added", "modified", "deleted"] = "modified"


class TimelineRoundDTO(BaseModel):
    """一轮 = 一次执行。轮次不覆盖,上一轮的结论留在上一轮里。"""

    round: int
    key: str = ""
    at: str = ""
    finished_at: str = ""
    summary: str = ""
    verdicts: dict[str, int] = {}
    diff: list[RoundDiffDTO] = []
    segments: list[TimelineSegmentDTO] = []


class IssueTimelineDTO(BaseModel):
    """一个议题:头部结论 + 轮次。没有变更时 rounds 为空,不是 404。"""

    id: str
    number: int = 0
    title: str = ""
    topic: str = ""
    repo: str = ""
    state: IssueState
    state_reason: str = ""
    branch: TimelineBranchDTO | None = None
    rounds: list[TimelineRoundDTO] = []
    truncated: bool = False

# 等你做什么:钉在一条具体的变更单元上,不是一句"待处理"。
IssueAction = Literal["approve", "investigate", ""]


class IssueCardDTO(BaseModel):
    """列表上的一行。三个状态由后端给,与详情页同一套判定。"""

    id: str
    number: int = 0
    title: str = ""
    repo: str = ""
    topic: str = ""
    state: IssueState
    state_reason: str = ""
    action: IssueAction = ""
    unit_id: str = ""
    rounds: int = 0
    waiting_since: str = ""
    updated_at: str = ""
    conclusion: str = ""
    # 空串 = 还没有任何变更。空不是第七种结论,所以单独留在联合类型里。
    verdict: Verdict | Literal[""] = ""
    undoable: bool = False
    undo_reason: str = ""
    branch: str = ""
    pull: str = ""


class IssueBoardDTO(BaseModel):
    """议题板:三段、三个数。首页就是它。"""

    items: list[IssueCardDTO] = []
    counts: dict[str, int] = {}
    total: int = 0


class ContinueRoundDTO(BaseModel):
    """人要求接着这条线再改一轮。

    上限 500:事故只存 signal_title(String(512)),再长会被悄悄截断——宁可在这里
    就说"太长了",也不要让人写下的话在时间线上少一截。
    """

    instruction: str = Field(..., min_length=1, max_length=500)


class ContinuedDTO(BaseModel):
    """已经开始排这一轮。轮次本身要等它跑起来才存在,所以这里不给轮号。"""

    workflow_id: str
    status: str = "queued"
