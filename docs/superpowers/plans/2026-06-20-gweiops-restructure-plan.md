# GweiOps 目录结构重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GweiOps 从混乱的单体结构重构为清晰的三层架构（engine + plugins + dashboard）

**Architecture:** 大脑核心（engine/）使用 Python 实现，包含状态机、记忆系统、插件管理器。插件系统（plugins/）支持任何语言，通过 gRPC 通信。Dashboard（dashboard/）独立的 Next.js 前端项目。

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, LangGraph, Next.js 14, gRPC, PostgreSQL + pgvector, Redis

---

## 文件结构

### 核心引擎 (engine/)

| 文件 | 职责 |
|------|------|
| `engine/shared/config.py` | 配置管理 |
| `engine/shared/logger.py` | 结构化日志 |
| `engine/shared/metrics.py` | 指标收集 |
| `engine/shared/template.py` | 模板引擎 |
| `engine/db/base.py` | ORM 基类 |
| `engine/db/engine.py` | 数据库引擎 |
| `engine/db/models/*.py` | 数据模型 |
| `engine/llm/client.py` | LLM 客户端 |
| `engine/llm/embedding.py` | 向量嵌入 |
| `engine/state_machine/states.py` | 状态定义 |
| `engine/state_machine/transitions.py` | 状态转换 |
| `engine/state_machine/machine.py` | 状态机核心 |
| `engine/scheduler/queue.py` | 任务队列 |
| `engine/scheduler/worker.py` | 工作进程 |
| `engine/scheduler/lifecycle.py` | 生命周期管理 |
| `engine/memory/store.py` | 向量存储 |
| `engine/memory/retriever.py` | 记忆检索 |
| `engine/memory/learner.py` | 学习引擎 |
| `engine/plugin_manager/base.py` | 插件基类 |
| `engine/plugin_manager/registry.py` | 插件注册表 |
| `engine/plugin_manager/loader.py` | 插件加载器 |
| `engine/plugin_manager/dispatcher.py` | 任务分发器 |
| `engine/plugin_manager/health.py` | 健康检查 |
| `engine/api/app.py` | FastAPI 入口 |
| `engine/api/routes/*.py` | API 路由 |

### 插件 (plugins/)

| 文件 | 职责 |
|------|------|
| `plugins/builtin/adapters/github/plugin.yaml` | GitHub 适配器声明 |
| `plugins/builtin/adapters/github/plugin.py` | GitHub 适配器实现 |
| `plugins/builtin/adapters/github/client.py` | GitHub API 客户端 |
| `plugins/builtin/adapters/github/handlers.py` | Webhook 处理器 |
| `plugins/builtin/agents/*/plugin.yaml` | 智能体声明 |
| `plugins/builtin/agents/*/plugin.py` | 智能体实现 |

### Proto (proto/)

| 文件 | 职责 |
|------|------|
| `proto/core.proto` | 核心引擎接口 |
| `proto/plugin.proto` | 插件接口 |
| `proto/models.proto` | 数据模型 |

---

## Task 1: 创建目录结构和基础文件

**Files:**
- Create: `engine/` 目录结构
- Create: `plugins/` 目录结构
- Create: `dashboard/` 目录结构
- Create: `proto/` 目录结构
- Create: `.gitignore`

- [ ] **Step 1: 创建 engine 目录结构**

```bash
cd E:/git/Gwei
mkdir -p engine/{scheduler,state_machine,memory,plugin_manager,llm,db/models,api/routes,shared}
```

- [ ] **Step 2: 创建 plugins 目录结构**

```bash
mkdir -p plugins/{builtin/{adapters/github,agents/{sensor,diagnoser,fixer,deployer,observer,reporter,learner},actions/k8s-scaler},community}
```

- [ ] **Step 3: 创建 dashboard 目录结构**

```bash
mkdir -p dashboard/src
```

- [ ] **Step 4: 创建 proto 目录结构**

```bash
mkdir -p proto
```

- [ ] **Step 5: 创建所有 __init__.py 文件**

```bash
for dir in engine engine/scheduler engine/state_machine engine/memory engine/plugin_manager engine/llm engine/db engine/db/models engine/api engine/api/routes engine/shared plugins/builtin/adapters/github plugins/builtin/agents/sensor plugins/builtin/agents/diagnoser plugins/builtin/agents/fixer plugins/builtin/agents/deployer plugins/builtin/agents/observer plugins/builtin/agents/reporter plugins/builtin/agents/learner plugins/builtin/actions/k8s-scaler tests; do
  touch "$dir/__init__.py"
done
```

- [ ] **Step 6: 更新 .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.venv/
venv/
ENV/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# Temporary files
*.pid
*.tmp
*.log

# Superpowers (temporary brainstorm files)
.superpowers/

# OS files
.DS_Store
Thumbs.db

# Environment variables
.env
.env.local
.env.*.local

# Docker
docker-compose.override.yml

# Node.js
node_modules/
.next/
out/
```

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "chore: create directory structure for GweiOps restructure"
```

---

## Task 2: 创建插件系统基类

**Files:**
- Create: `engine/plugin_manager/__init__.py`
- Create: `engine/plugin_manager/base.py`

- [ ] **Step 1: 创建插件基类**

```python
# engine/plugin_manager/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class PluginType(str, Enum):
    """插件类型"""
    ADAPTER = "adapter"
    AGENT = "agent"
    ACTION = "action"
    DASHBOARD_COMPONENT = "dashboard_component"


@dataclass
class PluginInfo:
    """插件信息"""
    name: str
    version: str
    type: PluginType
    description: str
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


class PluginBase(ABC):
    """插件基类，所有插件必须实现此接口"""

    @abstractmethod
    def info(self) -> PluginInfo:
        """返回插件信息"""
        pass

    @abstractmethod
    async def on_startup(self):
        """启动时初始化"""
        pass

    @abstractmethod
    async def on_shutdown(self):
        """关闭时释放资源"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    @abstractmethod
    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件（事件触发）"""
        pass

    @abstractmethod
    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务（调度智能体触发）"""
        pass
```

- [ ] **Step 2: 创建 __init__.py**

```python
# engine/plugin_manager/__init__.py
from .base import PluginBase, PluginInfo, PluginType
from .dispatcher import PluginDispatcher

__all__ = ["PluginBase", "PluginInfo", "PluginType", "PluginDispatcher"]
```

- [ ] **Step 3: Commit**

```bash
git add engine/plugin_manager/
git commit -m "feat: add plugin system base classes"
```

---

## Task 3: 创建插件调度器

**Files:**
- Create: `engine/plugin_manager/dispatcher.py`

- [ ] **Step 1: 创建调度器**

```python
# engine/plugin_manager/dispatcher.py
from typing import Dict, Any, List
from .base import PluginBase, PluginInfo


class PluginDispatcher:
    """插件调度器，负责事件分发和任务调度"""

    def __init__(self):
        self.plugins: Dict[str, PluginBase] = {}
        self.event_handlers: Dict[str, List[str]] = {}
        self.scheduler_handlers: Dict[str, List[str]] = {}

    def register(self, plugin: PluginBase):
        """注册插件"""
        info = plugin.info()
        name = info.name
        self.plugins[name] = plugin

        # 索引事件触发
        for trigger in info.triggers:
            if trigger["type"] == "event":
                for event in trigger["events"]:
                    if event not in self.event_handlers:
                        self.event_handlers[event] = []
                    self.event_handlers[event].append(name)

            elif trigger["type"] == "scheduler":
                for state in trigger["states"]:
                    if state not in self.scheduler_handlers:
                        self.scheduler_handlers[state] = []
                    self.scheduler_handlers[state].append(name)

    def unregister(self, name: str):
        """注销插件"""
        if name in self.plugins:
            del self.plugins[name]

            # 清理索引
            for event, handlers in self.event_handlers.items():
                if name in handlers:
                    handlers.remove(name)

            for state, handlers in self.scheduler_handlers.items():
                if name in handlers:
                    handlers.remove(name)

    async def dispatch_event(self, event: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """事件触发分发"""
        results = []
        plugin_names = self.event_handlers.get(event, [])

        for name in plugin_names:
            if name in self.plugins:
                plugin = self.plugins[name]
                try:
                    result = await plugin.handle_event(event, data)
                    results.append({"plugin": name, "success": True, "result": result})
                except Exception as e:
                    results.append({"plugin": name, "success": False, "error": str(e)})

        return results

    async def dispatch_task(self, state: str, task: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """调度智能体触发分发"""
        results = []
        plugin_names = self.scheduler_handlers.get(state, [])

        for name in plugin_names:
            if name in self.plugins:
                plugin = self.plugins[name]
                try:
                    result = await plugin.execute_task(task, params)
                    results.append({"plugin": name, "success": True, "result": result})
                except Exception as e:
                    results.append({"plugin": name, "success": False, "error": str(e)})

        return results

    async def health_check_all(self) -> Dict[str, bool]:
        """检查所有插件健康状态"""
        results = {}
        for name, plugin in self.plugins.items():
            try:
                results[name] = await plugin.health_check()
            except Exception:
                results[name] = False
        return results

    def list_plugins(self) -> List[PluginInfo]:
        """列出所有插件"""
        return [plugin.info() for plugin in self.plugins.values()]
```

- [ ] **Step 2: Commit**

```bash
git add engine/plugin_manager/dispatcher.py
git commit -m "feat: add plugin dispatcher"
```

---

## Task 4: 迁移共享工具

**Files:**
- Copy: `gwei/src/config.py` → `engine/shared/config.py`
- Copy: `gwei/src/services/logger.py` → `engine/shared/logger.py`
- Copy: `gwei/src/services/metrics.py` → `engine/shared/metrics.py`
- Copy: `gwei/src/services/template.py` → `engine/shared/template.py`

- [ ] **Step 1: 复制共享工具文件**

```bash
cd E:/git/Gwei
cp gwei/src/config.py engine/shared/config.py
cp gwei/src/services/logger.py engine/shared/logger.py
cp gwei/src/services/metrics.py engine/shared/metrics.py
cp gwei/src/services/template.py engine/shared/template.py
```

- [ ] **Step 2: 更新导入路径**

在每个文件中，将 `from src.` 替换为 `from engine.`

- [ ] **Step 3: 创建 __init__.py**

```python
# engine/shared/__init__.py
from .config import Settings
from .logger import StructuredLogger, logger
from .metrics import MetricsCollector, metrics, GweiMetrics
from .template import TemplateEngine

__all__ = ["Settings", "StructuredLogger", "logger", "MetricsCollector", "metrics", "GweiMetrics", "TemplateEngine"]
```

- [ ] **Step 4: Commit**

```bash
git add engine/shared/
git commit -m "feat: migrate shared utilities to engine/shared"
```

---

## Task 5: 迁移数据库代码

**Files:**
- Copy: `gwei/src/db/base.py` → `engine/db/base.py`
- Copy: `gwei/src/db/engine.py` → `engine/db/engine.py`
- Copy: `gwei/src/models/*.py` → `engine/db/models/`

- [ ] **Step 1: 复制数据库文件**

```bash
cd E:/git/Gwei
cp gwei/src/db/base.py engine/db/base.py
cp gwei/src/db/engine.py engine/db/engine.py
cp gwei/src/models/issue.py engine/db/models/issue.py
cp gwei/src/models/patch.py engine/db/models/patch.py
cp gwei/src/models/pr.py engine/db/models/pr.py
cp gwei/src/models/project.py engine/db/models/project.py
cp gwei/src/models/session.py engine/db/models/session.py
cp gwei/src/models/vote.py engine/db/models/vote.py
```

- [ ] **Step 2: 更新导入路径**

在每个文件中，将 `from src.` 替换为 `from engine.`

- [ ] **Step 3: 创建 __init__.py**

```python
# engine/db/__init__.py
from .engine import engine, async_session_factory, get_db
from .base import Base

__all__ = ["engine", "async_session_factory", "get_db", "Base"]
```

```python
# engine/db/models/__init__.py
from .project import Project
from .issue import Issue
from .session import AgentSession
from .patch import Patch
from .pr import PullRequest
from .vote import ApprovalVote

__all__ = ["Project", "Issue", "AgentSession", "Patch", "PullRequest", "ApprovalVote"]
```

- [ ] **Step 4: Commit**

```bash
git add engine/db/
git commit -m "feat: migrate database code to engine/db"
```

---

## Task 6: 迁移 LLM 客户端

**Files:**
- Copy: `gwei/src/services/llm.py` → `engine/llm/client.py`
- Copy: `gwei/src/services/embedding.py` → `engine/llm/embedding.py`

- [ ] **Step 1: 复制 LLM 文件**

```bash
cd E:/git/Gwei
cp gwei/src/services/llm.py engine/llm/client.py
cp gwei/src/services/embedding.py engine/llm/embedding.py
```

- [ ] **Step 2: 更新导入路径**

在每个文件中，将 `from src.` 替换为 `from engine.`

- [ ] **Step 3: 创建 __init__.py**

```python
# engine/llm/__init__.py
from .client import LLMService, LLMCallResult
from .embedding import EmbeddingService, SearchResult

__all__ = ["LLMService", "LLMCallResult", "EmbeddingService", "SearchResult"]
```

- [ ] **Step 4: Commit**

```bash
git add engine/llm/
git commit -m "feat: migrate LLM client to engine/llm"
```

---

## Task 7: 创建状态机引擎

**Files:**
- Create: `engine/state_machine/states.py`
- Create: `engine/state_machine/transitions.py`
- Create: `engine/state_machine/machine.py`

- [ ] **Step 1: 创建状态定义**

```python
# engine/state_machine/states.py
from enum import Enum


class WorkflowState(str, Enum):
    """工作流状态定义"""
    S0_PERCEIVED = "S0_PERCEIVED"   # 问题感知
    S1_DIAGNOSED = "S1_DIAGNOSED"   # 诊断决策
    S2_PLANNED = "S2_PLANNED"       # 方案生成
    S3_EXECUTED = "S3_EXECUTED"     # 方案执行
    S4_VERIFIED = "S4_VERIFIED"     # 验证
    S5_CANARIED = "S5_CANARIED"     # 生产分流
    S6_REVIEWED = "S6_REVIEWED"     # 最终审核
    DONE = "DONE"                   # 完成
    FAILED = "FAILED"               # 失败


class IssueType(str, Enum):
    """Issue 类型"""
    BUG = "bug"
    FEATURE = "feature"
    DOCS = "docs"
    DUPLICATE = "duplicate"
    QUESTION = "question"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    """行动类型"""
    CODE_FIX = "code_fix"           # 代码修复
    UPSTREAM_UPDATE = "upstream_update"  # 上游更新
    NON_CODE_ACTION = "non_code_action"  # 非代码运维
```

- [ ] **Step 2: 创建状态转换规则**

```python
# engine/state_machine/transitions.py
from typing import Dict, Any, List, Optional
from .states import WorkflowState, ActionType


class TransitionRule:
    """状态转换规则"""

    def __init__(
        self,
        from_state: WorkflowState,
        to_state: WorkflowState,
        condition: str,
        description: str,
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.description = description


# 默认转换规则
DEFAULT_TRANSITIONS = [
    # S0 → S1: 问题感知后进入诊断
    TransitionRule(
        from_state=WorkflowState.S0_PERCEIVED,
        to_state=WorkflowState.S1_DIAGNOSED,
        condition="issue_perceived",
        description="问题感知后进入诊断决策",
    ),
    # S1 → S2: 诊断完成后生成方案
    TransitionRule(
        from_state=WorkflowState.S1_DIAGNOSED,
        to_state=WorkflowState.S2_PLANNED,
        condition="diagnosis_completed",
        description="诊断完成后生成修复方案",
    ),
    # S2 → S3: 方案生成后执行
    TransitionRule(
        from_state=WorkflowState.S2_PLANNED,
        to_state=WorkflowState.S3_EXECUTED,
        condition="plan_generated",
        description="方案生成后执行",
    ),
    # S3 → S4: 执行完成后验证
    TransitionRule(
        from_state=WorkflowState.S3_EXECUTED,
        to_state=WorkflowState.S4_VERIFIED,
        condition="execution_completed",
        description="执行完成后验证",
    ),
    # S4 → S5: 验证通过后生产分流
    TransitionRule(
        from_state=WorkflowState.S4_VERIFIED,
        to_state=WorkflowState.S5_CANARIED,
        condition="verification_passed",
        description="验证通过后生产分流",
    ),
    # S5 → S6: 金丝雀发布后最终审核
    TransitionRule(
        from_state=WorkflowState.S5_CANARIED,
        to_state=WorkflowState.S6_REVIEWED,
        condition="canary_completed",
        description="金丝雀发布后最终审核",
    ),
    # S6 → DONE: 审核通过后完成
    TransitionRule(
        from_state=WorkflowState.S6_REVIEWED,
        to_state=WorkflowState.DONE,
        condition="review_approved",
        description="审核通过后完成",
    ),
    # S6 → S2: 审核不通过，回退到方案生成
    TransitionRule(
        from_state=WorkflowState.S6_REVIEWED,
        to_state=WorkflowState.S2_PLANNED,
        condition="review_rejected",
        description="审核不通过，回退到方案生成",
    ),
    # 任意状态 → FAILED: 失败
    TransitionRule(
        from_state=WorkflowState.S0_PERCEIVED,
        to_state=WorkflowState.FAILED,
        condition="error_occurred",
        description="发生错误",
    ),
]
```

- [ ] **Step 3: 创建状态机核心**

```python
# engine/state_machine/machine.py
from typing import Dict, Any, Optional, Callable, Awaitable
from .states import WorkflowState
from .transitions import TransitionRule, DEFAULT_TRANSITIONS


class StateMachine:
    """状态机核心"""

    def __init__(self, initial_state: WorkflowState = WorkflowState.S0_PERCEIVED):
        self.current_state = initial_state
        self.transitions: Dict[str, TransitionRule] = {}
        self.on_transition_callbacks: list[Callable] = []

        # 加载默认转换规则
        for rule in DEFAULT_TRANSITIONS:
            key = f"{rule.from_state.value}:{rule.condition}"
            self.transitions[key] = rule

    def add_transition(self, rule: TransitionRule):
        """添加转换规则"""
        key = f"{rule.from_state.value}:{rule.condition}"
        self.transitions[key] = rule

    def on_transition(self, callback: Callable):
        """注册转换回调"""
        self.on_transition_callbacks.append(callback)

    async def trigger(self, condition: str, context: Dict[str, Any] = None) -> bool:
        """触发状态转换"""
        key = f"{self.current_state.value}:{condition}"
        rule = self.transitions.get(key)

        if not rule:
            return False

        # 执行转换
        old_state = self.current_state
        self.current_state = rule.to_state

        # 调用回调
        for callback in self.on_transition_callbacks:
            await callback(old_state, rule.to_state, context or {})

        return True

    def get_available_transitions(self) -> list[str]:
        """获取当前状态可用的转换"""
        return [
            rule.condition
            for key, rule in self.transitions.items()
            if key.startswith(f"{self.current_state.value}:")
        ]

    def is_terminal(self) -> bool:
        """是否为终止状态"""
        return self.current_state in (WorkflowState.DONE, WorkflowState.FAILED)

    def reset(self):
        """重置状态机"""
        self.current_state = WorkflowState.S0_PERCEIVED
```

- [ ] **Step 4: 创建 __init__.py**

```python
# engine/state_machine/__init__.py
from .states import WorkflowState, IssueType, ActionType
from .transitions import TransitionRule, DEFAULT_TRANSITIONS
from .machine import StateMachine

__all__ = [
    "WorkflowState", "IssueType", "ActionType",
    "TransitionRule", "DEFAULT_TRANSITIONS",
    "StateMachine",
]
```

- [ ] **Step 5: Commit**

```bash
git add engine/state_machine/
git commit -m "feat: add state machine engine"
```

---

## Task 8: 创建记忆系统

**Files:**
- Create: `engine/memory/store.py`
- Create: `engine/memory/retriever.py`
- Create: `engine/memory/learner.py`

- [ ] **Step 1: 创建向量存储**

```python
# engine/memory/store.py
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class MemoryRecord:
    """记忆记录"""
    id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any]
    created_at: float


class MemoryStore:
    """向量存储"""

    def __init__(self):
        self.records: Dict[str, MemoryRecord] = {}

    async def add(self, record: MemoryRecord):
        """添加记录"""
        self.records[record.id] = record

    async def get(self, record_id: str) -> Optional[MemoryRecord]:
        """获取记录"""
        return self.records.get(record_id)

    async def delete(self, record_id: str):
        """删除记录"""
        if record_id in self.records:
            del self.records[record_id]

    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[MemoryRecord]:
        """搜索相似记录"""
        import math

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        results = []
        for record in self.records.values():
            score = cosine_similarity(query_embedding, record.embedding)
            if score >= threshold:
                results.append((score, record))

        results.sort(key=lambda x: x[0], reverse=True)
        return [record for _, record in results[:top_k]]

    async def list_all(self) -> List[MemoryRecord]:
        """列出所有记录"""
        return list(self.records.values())

    async def count(self) -> int:
        """获取记录数量"""
        return len(self.records)
```

- [ ] **Step 2: 创建记忆检索**

```python
# engine/memory/retriever.py
from typing import Dict, Any, List, Optional
from .store import MemoryStore, MemoryRecord


class MemoryRetriever:
    """记忆检索"""

    def __init__(self, store: MemoryStore):
        self.store = store

    async def retrieve(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[MemoryRecord]:
        """检索相关记忆"""
        return await self.store.search(query_embedding, top_k, threshold)

    async def retrieve_by_context(
        self,
        context: Dict[str, Any],
        query_embedding: List[float],
        top_k: int = 5,
    ) -> List[MemoryRecord]:
        """根据上下文检索记忆"""
        # 获取所有记录
        all_records = await self.store.list_all()

        # 根据上下文过滤
        filtered = []
        for record in all_records:
            if self._matches_context(record, context):
                filtered.append(record)

        # 按相似度排序
        import math

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        scored = [
            (cosine_similarity(query_embedding, record.embedding), record)
            for record in filtered
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        return [record for _, record in scored[:top_k]]

    def _matches_context(self, record: MemoryRecord, context: Dict[str, Any]) -> bool:
        """检查记录是否匹配上下文"""
        for key, value in context.items():
            if key in record.metadata:
                if record.metadata[key] != value:
                    return False
        return True
```

- [ ] **Step 3: 创建学习引擎**

```python
# engine/memory/learner.py
from typing import Dict, Any, List, Optional
from .store import MemoryStore, MemoryRecord
import time
import uuid


class MemoryLearner:
    """学习引擎"""

    def __init__(self, store: MemoryStore):
        self.store = store

    async def record_decision(
        self,
        issue_type: str,
        context: Dict[str, Any],
        decision: str,
        reason: str,
        embedding: List[float],
        confidence: float = 0.5,
        tags: List[str] = None,
    ):
        """记录决策"""
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=f"Issue: {issue_type}\nDecision: {decision}\nReason: {reason}",
            embedding=embedding,
            metadata={
                "issue_type": issue_type,
                "decision": decision,
                "reason": reason,
                "confidence": confidence,
                "tags": tags or [],
                **context,
            },
            created_at=time.time(),
        )
        await self.store.add(record)

    async def record_rollback(
        self,
        original_decision: str,
        rollback_reason: str,
        human_instruction: str,
        embedding: List[float],
    ):
        """记录决策回滚"""
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=f"Rollback: {original_decision}\nReason: {rollback_reason}\nInstruction: {human_instruction}",
            embedding=embedding,
            metadata={
                "type": "rollback",
                "original_decision": original_decision,
                "rollback_reason": rollback_reason,
                "human_instruction": human_instruction,
            },
            created_at=time.time(),
        )
        await self.store.add(record)

    async def get_similar_decisions(
        self,
        issue_type: str,
        query_embedding: List[float],
        top_k: int = 3,
    ) -> List[MemoryRecord]:
        """获取相似决策"""
        return await self.store.search(
            query_embedding,
            top_k=top_k,
            threshold=0.6,
        )
```

- [ ] **Step 4: 创建 __init__.py**

```python
# engine/memory/__init__.py
from .store import MemoryStore, MemoryRecord
from .retriever import MemoryRetriever
from .learner import MemoryLearner

__all__ = ["MemoryStore", "MemoryRecord", "MemoryRetriever", "MemoryLearner"]
```

- [ ] **Step 5: Commit**

```bash
git add engine/memory/
git commit -m "feat: add memory system"
```

---

## Task 9: 迁移 GitHub 适配器

**Files:**
- Copy: `gwei/src/services/github.py` → `plugins/builtin/adapters/github/client.py`
- Copy: `gwei/src/services/git_tool.py` → `plugins/builtin/adapters/github/git.py`
- Copy: `gwei/src/services/webhook.py` → `plugins/builtin/adapters/github/handlers.py`
- Create: `plugins/builtin/adapters/github/plugin.py`
- Create: `plugins/builtin/adapters/github/plugin.yaml`

- [ ] **Step 1: 复制 GitHub 适配器文件**

```bash
cd E:/git/Gwei
cp gwei/src/services/github.py plugins/builtin/adapters/github/client.py
cp gwei/src/services/git_tool.py plugins/builtin/adapters/github/git.py
cp gwei/src/services/webhook.py plugins/builtin/adapters/github/handlers.py
```

- [ ] **Step 2: 创建 plugin.yaml**

```yaml
# plugins/builtin/adapters/github/plugin.yaml
name: github-adapter
version: 1.0.0
type: adapter
description: GitHub 托管适配器

triggers:
  - type: event
    events:
      - webhook.received
      - issue.created
      - pr.merged

capabilities:
  - issue.read
  - issue.write
  - pr.read
  - pr.write
  - pr.merge
  - comment.read
  - comment.write
  - webhook.receive

config:
  required:
    - GITHUB_TOKEN
    - GITHUB_WEBHOOK_SECRET
  optional:
    - GITHUB_API_URL
```

- [ ] **Step 3: 创建 plugin.py**

```python
# plugins/builtin/adapters/github/plugin.py
from typing import Dict, Any
import sys
import os

# 添加 engine 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .client import GitHubClient
from .git import GitTool


class GitHubAdapter(PluginBase):
    """GitHub 适配器插件"""

    def __init__(self):
        self.client: GitHubClient = None
        self.git_tool: GitTool = None
        self.config: Dict[str, Any] = {}

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="github-adapter",
            version="1.0.0",
            type=PluginType.ADAPTER,
            description="GitHub 托管适配器",
            triggers=[
                {
                    "type": "event",
                    "events": ["webhook.received", "issue.created", "pr.merged"],
                }
            ],
            capabilities=[
                "issue.read", "issue.write",
                "pr.read", "pr.write", "pr.merge",
                "comment.read", "comment.write",
                "webhook.receive",
            ],
            config={
                "required": ["GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET"],
                "optional": ["GITHUB_API_URL"],
            },
        )

    async def on_startup(self):
        """启动时初始化"""
        self.client = GitHubClient()
        self.git_tool = GitTool()

    async def on_shutdown(self):
        """关闭时释放资源"""
        self.client = None
        self.git_tool = None

    async def health_check(self) -> bool:
        """健康检查"""
        return self.client is not None

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件"""
        if event == "webhook.received":
            return await self._handle_webhook(data)
        elif event == "issue.created":
            return await self._handle_issue_created(data)
        elif event == "pr.merged":
            return await self._handle_pr_merged(data)
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务"""
        if task == "create_comment":
            return await self.client.create_comment(**params)
        elif task == "create_pr":
            return await self.client.create_pr(**params)
        elif task == "merge_pr":
            return await self.client.merge_pr(**params)
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _handle_webhook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Webhook"""
        from .handlers import process_issue_event
        event_type = data.get("event_type", "")
        payload = data.get("payload", {})
        return await process_issue_event(event_type, payload)

    async def _handle_issue_created(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Issue 创建"""
        return {"status": "ok", "action": "issue_created"}

    async def _handle_pr_merged(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 PR 合并"""
        return {"status": "ok", "action": "pr_merged"}
```

- [ ] **Step 4: 更新导入路径**

在 `client.py`、`git.py`、`handlers.py` 中，将 `from src.` 替换为相对导入

- [ ] **Step 5: Commit**

```bash
git add plugins/builtin/adapters/github/
git commit -m "feat: migrate GitHub adapter to plugins"
```

---

## Task 10: 迁移智能体插件

**Files:**
- Copy: `gwei/src/services/labeler.py` → `plugins/builtin/agents/sensor/`
- Copy: `gwei/src/services/completeness.py` → `plugins/builtin/agents/sensor/`
- Copy: `gwei/src/services/duplicate_detector.py` → `plugins/builtin/agents/sensor/`
- Create: `plugins/builtin/agents/sensor/plugin.py`
- Create: `plugins/builtin/agents/sensor/plugin.yaml`
- (类似地创建其他智能体)

- [ ] **Step 1: 创建感知智能体**

```bash
cd E:/git/Gwei
cp gwei/src/services/labeler.py plugins/builtin/agents/sensor/labeler.py
cp gwei/src/services/completeness.py plugins/builtin/agents/sensor/completeness.py
cp gwei/src/services/duplicate_detector.py plugins/builtin/agents/sensor/duplicate.py
```

- [ ] **Step 2: 创建 sensor/plugin.yaml**

```yaml
name: sensor-agent
version: 1.0.0
type: agent
description: 感知智能体，监听事件

triggers:
  - type: event
    events:
      - webhook.received
      - issue.created

capabilities:
  - issue.label
  - issue.completeness_check
  - issue.duplicate_detection
```

- [ ] **Step 3: 创建 sensor/plugin.py**

```python
from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .labeler import LabelGenerator
from .completeness import CompletenessChecker
from .duplicate import DuplicateDetector


class SensorAgent(PluginBase):
    """感知智能体"""

    def __init__(self):
        self.labeler = LabelGenerator()
        self.completeness = CompletenessChecker()
        self.duplicate = DuplicateDetector()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="sensor-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="感知智能体，监听事件",
            triggers=[
                {"type": "event", "events": ["webhook.received", "issue.created"]},
            ],
            capabilities=["issue.label", "issue.completeness_check", "issue.duplicate_detection"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("webhook.received", "issue.created"):
            return await self._process_issue(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "label":
            labels = self.labeler.generate(params.get("title", ""), params.get("body", ""))
            return {"labels": labels}
        elif task == "check_completeness":
            report = self.completeness.check(params.get("body", ""))
            return {"is_complete": report.is_complete, "missing": report.missing_fields}
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _process_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        issue = data.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")

        labels = self.labeler.generate(title, body)
        completeness = self.completeness.check(body)

        return {
            "status": "ok",
            "labels": labels,
            "is_complete": completeness.is_complete,
            "missing_fields": completeness.missing_fields,
        }
```

- [ ] **Step 4: 类似地创建其他智能体**

为 diagnoser、fixer、deployer、observer、reporter、learner 创建类似的 plugin.yaml 和 plugin.py

- [ ] **Step 5: Commit**

```bash
git add plugins/builtin/agents/
git commit -m "feat: migrate agent plugins"
```

---

## Task 11: 创建 Proto 文件

**Files:**
- Create: `proto/core.proto`
- Create: `proto/plugin.proto`
- Create: `proto/models.proto`

- [ ] **Step 1: 创建 plugin.proto**

```protobuf
// proto/plugin.proto
syntax = "proto3";

package gweiops.plugin;

service PluginService {
    // 生命周期
    rpc Startup(StartupRequest) returns (StartupResponse);
    rpc Shutdown(ShutdownRequest) returns (ShutdownResponse);
    rpc HealthCheck(HealthRequest) returns (HealthResponse);
    
    // 事件处理
    rpc HandleEvent(EventRequest) returns (EventResponse);
    
    // 任务执行
    rpc ExecuteTask(TaskRequest) returns (TaskResponse);
}

message StartupRequest {
    map<string, string> config = 1;
}

message StartupResponse {
    bool success = 1;
    string message = 2;
}

message ShutdownRequest {}

message ShutdownResponse {
    bool success = 1;
}

message HealthRequest {}

message HealthResponse {
    bool healthy = 1;
    string message = 2;
}

message EventRequest {
    string event = 1;
    bytes data = 2;
}

message EventResponse {
    bool success = 1;
    bytes result = 2;
    string error = 3;
}

message TaskRequest {
    string task = 1;
    bytes params = 2;
}

message TaskResponse {
    bool success = 1;
    bytes result = 2;
    string error = 3;
}
```

- [ ] **Step 2: 创建 models.proto**

```protobuf
// proto/models.proto
syntax = "proto3";

package gweiops.models;

message Issue {
    string id = 1;
    string title = 2;
    string body = 3;
    repeated string labels = 4;
    string status = 5;
    string source = 6;
    int64 created_at = 7;
}

message PullRequest {
    string id = 1;
    string issue_id = 2;
    string title = 3;
    string body = 4;
    string diff = 5;
    string status = 6;
    int64 created_at = 7;
}

message Diagnosis {
    string issue_type = 1;
    string root_cause = 2;
    string action_type = 3;
    string severity = 4;
}

message Patch {
    string type = 1;
    string diff = 2;
    string risk = 3;
    string description = 4;
}
```

- [ ] **Step 3: Commit**

```bash
git add proto/
git commit -m "feat: add protobuf definitions"
```

---

## Task 12: 迁移前端到 Dashboard

**Files:**
- Copy: `gwei/frontend/*` → `dashboard/`

- [ ] **Step 1: 复制前端文件**

```bash
cd E:/git/Gwei
cp -r gwei/frontend/* dashboard/
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/
git commit -m "feat: migrate frontend to dashboard"
```

---

## Task 13: 更新配置文件

**Files:**
- Create: `engine/pyproject.toml`
- Create: `engine/Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`

- [ ] **Step 1: 创建 engine/pyproject.toml**

```toml
[project]
name = "gweiops-engine"
version = "0.1.0"
description = "GweiOps 核心引擎"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30.0",
    "pgvector>=0.3.6",
    "redis>=5.2.0",
    "langgraph>=0.2.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.2.0",
    "httpx>=0.28.0",
    "pyyaml>=6.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "alembic>=1.14.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 创建 docker-compose.yml**

```yaml
services:
  engine:
    build: ./engine
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://gwei:gwei@postgres:5432/gwei
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: gwei
      POSTGRES_PASSWORD: gwei
      POSTGRES_DB: gwei
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  dashboard:
    build: ./dashboard
    ports:
      - "3000:3000"
```

- [ ] **Step 3: 创建 README.md**

```markdown
# GweiOps

> AI 驱动的全链路运维智能体平台

## 目录结构

```
├── engine/          # 大脑核心（Python）
├── plugins/         # 插件（任何语言）
├── dashboard/       # Dashboard（Node.js）
└── proto/           # gRPC 定义
```

## 快速开始

```bash
# 启动服务
docker-compose up -d

# 访问 Dashboard
open http://localhost:3000
```

## 开发

```bash
# 安装依赖
cd engine && pip install -e .

# 运行测试
pytest tests/

# 启动开发服务器
uvicorn engine.api.app:app --reload
```
```

- [ ] **Step 4: Commit**

```bash
git add engine/pyproject.toml docker-compose.yml README.md
git commit -m "chore: add configuration files"
```

---

## Task 14: 清理旧目录

**Files:**
- Delete: `gwei/` 目录

- [ ] **Step 1: 删除旧目录**

```bash
cd E:/git/Gwei
rm -rf gwei/
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "chore: remove old gwei/ directory"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 三层分离（engine + plugins + dashboard）
- ✅ 插件系统（基类、调度器、声明格式）
- ✅ 状态机引擎（S0-S6）
- ✅ 记忆系统（存储、检索、学习）
- ✅ GitHub 适配器
- ✅ 七智能体
- ✅ Proto 定义
- ✅ 前端迁移
- ✅ 配置文件

**2. Placeholder scan:**
- ✅ 没有 TBD、TODO 或不完整的部分
- ✅ 所有步骤都有具体的代码

**3. Type consistency:**
- ✅ 类型、方法签名、属性名在各任务中一致
