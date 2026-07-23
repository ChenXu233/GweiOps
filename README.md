# GweiOps

> AI 驱动的全链路运维智能体平台

**GweiOps —— 摆渡未济，恒守既济。**

├── engine/          # 大脑核心（Python FastAPI）
├── frontend/        # 前端（Nuxt 3 + Vue SSR）
├── plugins/         # 插件（任何语言）
└── proto/           # gRPC 定义
```

## 快速开始

### 使用 Docker（开发）

```bash
# 启动全部服务（自动加载 docker-compose.override.yml 开发配置）
docker compose up

# 访问 API
open http://localhost:8000/docs

# 访问前端
open http://localhost:3000
```

### 使用 Docker（生产）

```bash
# 创建生产环境变量
cp .env.prod.example .env.prod
# 编辑 .env.prod 填入 POSTGRES_PASSWORD 等必填项

# 启动服务
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 手动安装

```bash
# 安装后端依赖
cd engine
pip install -e .

# 运行测试
pytest tests/

# 启动开发服务器
uvicorn engine.api.app:app --reload

# 安装前端依赖
cd frontend
pnpm install

# 启动前端开发服务器
cd apps/selfhost
pnpm dev
```

## 核心组件

### engine/ - 大脑核心

| 组件 | 职责 |
|------|------|
| `scheduler/` | 统一调度层 |
| `state_machine/` | 状态机引擎（S0-S6） |
| `memory/` | 记忆系统 |
| `plugin_manager/` | 插件调度器 |
| `llm/` | LLM 客户端 |
| `db/` | 数据库 |
| `api/` | HTTP API |
| `shared/` | 共享工具 |

### plugins/ - 插件系统

| 类型 | 说明 |
|------|------|
| `adapters/` | 平台适配器（GitHub、GitLab、Jenkins...） |
| `agents/` | 智能体（感知、诊断、修复、部署、观测、汇报、学习） |
| `actions/` | 运维动作（K8s 扩容、流量调度...） |

### dashboard/ - Dashboard

Next.js 前端项目，提供态势感知面板。

### proto/ - gRPC 定义

语言无关的接口定义，支持任何语言实现插件。

## 插件开发

### 插件声明

```yaml
# plugin.yaml
name: my-plugin
version: 1.0.0
type: adapter
description: My custom adapter

triggers:
  - type: event
    events:
      - webhook.received

capabilities:
  - issue.read
  - issue.write
```

### 插件基类

```python
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

class MyPlugin(PluginBase):
    def info(self) -> PluginInfo:
        return PluginInfo(
            name="my-plugin",
            version="1.0.0",
            type=PluginType.ADAPTER,
            description="My custom adapter",
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ok"}

    async def execute_task(self, task: str, params: dict) -> dict:
        return {"status": "ok"}
```

## 架构设计

详见 [设计文档](docs/superpowers/specs/2026-06-20-gweiops-restructure-design.md)

## 许可证

- engine/: AGPL-3.0
- dashboard/: FSL-1.1-ALv2
- plugins/builtin/: Apache-2.0
- plugins/community/: MIT
- proto/: MIT
