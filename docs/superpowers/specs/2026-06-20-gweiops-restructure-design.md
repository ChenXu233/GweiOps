# GweiOps 目录结构重构设计文档

**文档版本**：v1.0  
**最后更新**：2026-06-20  
**作者**：GweiOps Team

---

## 一、问题诊断

当前 `gwei/` 目录存在以下致命问题：

1. **`gwei/gwei/` 嵌套**：`E:\git\Gwei\gwei\` 两层无意义嵌套
2. **`src/` 命名垃圾**：不反映任何业务含义
3. **`services/` 是垃圾桶**：20 个文件堆在一起，毫无组织
4. **导入路径丑陋**：`from src.xxx` 无意义前缀
5. **缺少 `.gitignore`**：`__pycache__`、`.superpowers/` 被提交
6. **两个 `docs/`**：`docs/` 和 `gwei/docs/` 混淆
7. **前端不独立**：嵌套在 `gwei/frontend/`，被 Python 项目污染

---

## 二、设计目标

1. **三层分离**：engine + plugins + dashboard
2. **统一插件**：所有扩展都是插件，通过声明接口区分类型
3. **语言无关**：大脑用 Python，插件用任何语言
4. **gRPC 通信**：默认 gRPC，可支持 HTTP
5. **事件驱动**：支持事件触发和调度智能体触发

---

## 三、目录结构

```
E:\git\Gwei\
├── README.md
├── .gitignore
├── pyproject.toml
├── docker-compose.yml
│
├── proto/                             # gRPC 定义（语言无关）
│   ├── core.proto                     # 核心引擎接口
│   ├── plugin.proto                   # 插件接口
│   ├── models.proto                   # 数据模型
│   └── build.sh                       # 生成各语言代码
│
├── engine/                            # 大脑核心（Python）
│   ├── pyproject.toml
│   ├── Dockerfile
│   │
│   ├── scheduler/                     # 统一调度层
│   │   ├── __init__.py
│   │   ├── queue.py                   # 任务队列
│   │   ├── worker.py                  # 工作进程
│   │   └── lifecycle.py               # Agent 生命周期
│   │
│   ├── state_machine/                 # 状态机引擎
│   │   ├── __init__.py
│   │   ├── machine.py                 # 状态机核心
│   │   ├── states.py                  # S0-S6 状态定义
│   │   └── transitions.py             # 状态转换规则
│   │
│   ├── memory/                        # 记忆系统
│   │   ├── __init__.py
│   │   ├── store.py                   # 向量存储
│   │   ├── retriever.py               # 记忆检索
│   │   └── learner.py                 # 学习引擎
│   │
│   ├── plugin_manager/                # 插件调度器
│   │   ├── __init__.py
│   │   ├── base.py                    # 插件基类
│   │   ├── registry.py                # 插件注册表
│   │   ├── loader.py                  # 插件加载器
│   │   ├── dispatcher.py              # 任务分发器
│   │   └── health.py                  # 健康检查
│   │
│   ├── llm/                           # LLM 客户端
│   │   ├── __init__.py
│   │   ├── client.py
│   │   └── embedding.py
│   │
│   ├── db/                            # 数据库
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── base.py
│   │   └── models/
│   │
│   ├── api/                           # HTTP API
│   │   ├── __init__.py
│   │   ├── app.py
│   │   └── routes/
│   │
│   └── shared/                        # 共享工具
│       ├── __init__.py
│       ├── config.py
│       ├── logger.py
│       └── metrics.py
│
├── plugins/                           # 所有插件
│   │
│   ├── builtin/                       # 内置插件
│   │   │
│   │   ├── adapters/                  # 适配器插件
│   │   │   └── github/
│   │   │       ├── plugin.yaml
│   │   │       ├── plugin.py
│   │   │       ├── client.py
│   │   │       ├── handlers.py
│   │   │       ├── Dockerfile
│   │   │       └── requirements.txt
│   │   │
│   │   ├── agents/                    # 智能体插件
│   │   │   ├── sensor/                # 感知智能体
│   │   │   ├── diagnoser/             # 诊断智能体
│   │   │   ├── fixer/                 # 修复智能体
│   │   │   ├── deployer/              # 部署智能体
│   │   │   ├── observer/              # 观测智能体
│   │   │   ├── reporter/              # 汇报智能体
│   │   │   └── learner/               # 学习智能体
│   │   │
│   │   └── actions/                   # 运维动作插件
│   │       └── k8s-scaler/
│   │
│   └── community/                     # 社区插件
│       └── .gitkeep
│
├── dashboard/                         # Dashboard（Node.js）
│   ├── package.json
│   ├── Dockerfile
│   └── src/
│
└── tests/                             # 集成测试
    ├── conftest.py
    └── test_e2e/
```

---

## 四、插件系统设计

### 4.1 插件类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **adapter** | 平台适配器 | GitHub、GitLab、Jenkins、ArgoCD |
| **agent** | 智能体 | 感知、诊断、修复、部署、观测、汇报、学习 |
| **action** | 运维动作 | K8s 扩容、流量调度、配置变更 |
| **dashboard_component** | Dashboard 组件 | 面板、图表 |

### 4.2 插件声明格式

```yaml
# plugin.yaml
name: github-adapter
version: 1.0.0
type: adapter
description: GitHub 托管适配器

# 触发方式声明
triggers:
  - type: event
    events:
      - webhook.received
      - issue.created
      - pr.merged
  - type: scheduler
    states:
      - S0_PERCEIVED
      - S3_EXECUTED

# 能力声明
capabilities:
  - issue.read
  - issue.write
  - pr.read
  - pr.write

# 配置
config:
  required:
    - GITHUB_TOKEN
    - GITHUB_WEBHOOK_SECRET
```

### 4.3 插件基类

```python
# engine/plugin_manager/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any

class PluginBase(ABC):
    """插件基类"""
    
    @abstractmethod
    def info(self) -> Dict[str, Any]:
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

### 4.4 触发方式

| 方式 | 说明 |
|------|------|
| **事件触发** | 外部事件 → 调度器 → 匹配插件 → 执行 |
| **调度智能体触发** | 状态机 → 调度器 → 选择插件 → 执行 |

### 4.5 插件发现机制

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **目录扫描** | 扫描 plugins/ 目录，自动加载 plugin.yaml | builtin 插件 |
| **动态注册** | 插件启动时向大脑注册自己 | 远程插件 |
| **手动注册** | 在配置文件中手动注册插件端点 | 同机/IP 插件 |

### 4.6 插件生命周期

```
启动 → 初始化 → 就绪 → 运行 → 暂停 → 恢复 → 停机
```

| 阶段 | 说明 |
|------|------|
| **启动** | 插件进程启动，加载配置 |
| **初始化** | 连接外部服务，注册到大脑 |
| **就绪** | 健康检查通过，可以接收任务 |
| **运行** | 正常处理任务 |
| **暂停** | 正在进行中的任务完成，不接收新任务 |
| **恢复** | 从暂停状态恢复 |
| **停机** | 优雅关闭，释放资源 |

---

## 五、核心组件设计

### 5.1 scheduler（统一调度层）

| 文件 | 职责 |
|------|------|
| `queue.py` | 任务队列，支持优先级和延迟 |
| `worker.py` | 工作进程，执行任务 |
| `lifecycle.py` | Agent 生命周期管理 |

### 5.2 state_machine（状态机引擎）

| 文件 | 职责 |
|------|------|
| `machine.py` | 状态机核心，管理状态转换 |
| `states.py` | S0-S6 状态定义 |
| `transitions.py` | 状态转换规则，支持回滚 |

状态定义：

```python
class WorkflowState(str, Enum):
    S0_PERCEIVED = "S0_PERCEIVED"   # 问题感知
    S1_DIAGNOSED = "S1_DIAGNOSED"   # 诊断决策
    S2_PLANNED = "S2_PLANNED"       # 方案生成
    S3_EXECUTED = "S3_EXECUTED"     # 方案执行
    S4_VERIFIED = "S4_VERIFIED"     # 验证
    S5_CANARIED = "S5_CANARIED"     # 生产分流
    S6_REVIEWED = "S6_REVIEWED"     # 最终审核
    DONE = "DONE"                   # 完成
    FAILED = "FAILED"               # 失败
```

### 5.3 memory（记忆系统）

| 文件 | 职责 |
|------|------|
| `store.py` | 向量存储，支持 pgvector |
| `retriever.py` | 记忆检索，相似度搜索 |
| `learner.py` | 学习引擎，记录决策回滚 |

### 5.4 plugin_manager（插件调度器）

| 文件 | 职责 |
|------|------|
| `base.py` | 插件基类定义 |
| `registry.py` | 插件注册表 |
| `loader.py` | 插件加载器，支持目录扫描 |
| `dispatcher.py` | 任务分发器，支持事件和调度触发 |
| `health.py` | 健康检查，支持自动重启 |

### 5.5 llm（LLM 客户端）

| 文件 | 职责 |
|------|------|
| `client.py` | LLM 调用封装，支持重试和指数退避 |
| `embedding.py` | 向量嵌入，支持批量处理 |

### 5.6 db（数据库）

| 文件 | 职责 |
|------|------|
| `engine.py` | 数据库引擎，连接池管理 |
| `base.py` | ORM 基类 |
| `models/` | 数据模型定义 |

### 5.7 api（HTTP API）

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI 入口 |
| `routes/` | 路由定义 |

### 5.8 shared（共享工具）

| 文件 | 职责 |
|------|------|
| `config.py` | 配置管理 |
| `logger.py` | 结构化日志 |
| `metrics.py` | 指标收集 |

---

## 六、MVP 范围

### 6.1 内置插件

| 插件 | 类型 | 职责 |
|------|------|------|
| **github-adapter** | adapter | GitHub 适配器，接收 Webhook，操作 PR |
| **sensor-agent** | agent | 感知智能体，监听事件 |
| **diagnoser-agent** | agent | 诊断智能体，分析根因 |
| **fixer-agent** | agent | 修复智能体，生成方案 |
| **deployer-agent** | agent | 部署智能体，指挥 CI/CD |
| **observer-agent** | agent | 观测智能体，轮询指标 |
| **reporter-agent** | agent | 汇报智能体，推送通知 |
| **learner-agent** | agent | 学习智能体，记录决策 |

### 6.2 核心功能

- [x] 状态机引擎（S0-S6）
- [x] 插件管理器（注册、加载、调度、健康检查）
- [x] 记忆系统（向量存储、检索、学习）
- [x] LLM 客户端（调用、嵌入）
- [x] 数据库（PostgreSQL + pgvector）
- [x] HTTP API（FastAPI）
- [x] Dashboard（Next.js）

---

## 七、通信协议

### 7.1 gRPC 服务定义

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
```

### 7.2 HTTP 兼容

- 使用 openapi.json 声明接口
- 支持 HTTP/JSON 作为备选通信方式

---

## 八、部署架构

### 8.1 Docker Compose

```yaml
services:
  # 大脑核心
  engine:
    build: ./engine
    ports:
      - "8000:8000"
  
  # 内置插件
  github-adapter:
    build: ./plugins/builtin/adapters/github
    ports:
      - "8081:8081"
  
  sensor-agent:
    build: ./plugins/builtin/agents/sensor
    ports:
      - "8082:8082"
  
  # ... 其他插件
  
  # Dashboard
  dashboard:
    build: ./dashboard
    ports:
      - "3000:3000"
  
  # 基础设施
  postgres:
    image: pgvector/pgvector:pg16
  
  redis:
    image: redis:7-alpine
```

### 8.2 服务发现

- builtin 插件：目录扫描
- 远程插件：动态注册
- 同机插件：手动注册

---

## 九、许可证策略

| 组件 | 许可证 | 说明 |
|------|--------|------|
| **engine/** | AGPL | 核心引擎，强开源 |
| **plugins/builtin/** | MIT | 内置插件，鼓励使用 |
| **plugins/community/** | MIT | 社区插件，鼓励贡献 |
| **dashboard/** | MIT | 前端独立 |
| **proto/** | MIT | 接口定义，语言无关 |

---

## 十、迁移计划

### 10.1 阶段 1：创建新目录结构

1. 创建 `engine/` 目录结构
2. 创建 `plugins/` 目录结构
3. 创建 `dashboard/` 目录结构
4. 更新 `.gitignore`

### 10.2 阶段 2：迁移代码

1. 迁移核心代码到 `engine/`
2. 迁移插件代码到 `plugins/builtin/`
3. 迁移前端到 `dashboard/`
4. 更新所有导入路径

### 10.3 阶段 3：更新配置

1. 更新 `pyproject.toml`
2. 更新 `Dockerfile`
3. 更新 `docker-compose.yml`

### 10.4 阶段 4：清理

1. 删除旧的 `gwei/` 目录
2. 删除 `__pycache__/`
3. 删除 `.superpowers/`

---

## 十一、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 导入路径遗漏 | 使用 IDE 重构工具，运行测试验证 |
| 测试失败 | 逐步迁移，每步验证 |
| Docker 构建失败 | 更新 Dockerfile 路径 |
| 插件通信问题 | 定义清晰的 gRPC 接口 |

---

## 十二、总结

本次重构将 GweiOps 从混乱的单体结构转变为清晰的三层架构：

1. **engine/**：大脑核心，负责调度、状态机、记忆、插件管理
2. **plugins/**：所有插件，支持任何语言，通过 gRPC 通信
3. **dashboard/**：独立的前端项目

这种架构符合白皮书的设计，支持：
- 语言无关的插件系统
- 事件驱动和调度智能体触发
- 优雅停机和滚动升级
- 社区贡献和生态扩展
