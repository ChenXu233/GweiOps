# GweiOps

> AI 驱动的全链路运维智能体平台

**GweiOps —— 摆渡未济，恒守既济。**

GweiOps 由 Python 引擎、Nuxt 3 前端、插件系统与 gRPC 契约组成。

```text
engine/     Python FastAPI 核心（工作流、插件、API、数据）
frontend/   Nuxt 3 单应用（selfhost / saas 两种部署档）
plugins/    插件（adapters / agents / actions）
proto/      gRPC 插件契约
docs/       文档（索引见 docs/README.md）
```

## 快速开始

### Docker(开发)

```bash
docker compose up
# API:   http://localhost:8000/docs
# 前端:  http://localhost:3000
```

### Docker(生产)

```bash
cp .env.prod.example .env.prod
# 编辑 .env.prod,填入 POSTGRES_PASSWORD 等必填项
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 手动安装

```bash
# 后端(仓库根目录)
cd engine && pip install -e ".[dev]" && cd ..
pytest tests/ -q
uvicorn engine.api.app:app --reload

# 前端
cd frontend
pnpm install
pnpm dev:selfhost
```

## 文档

从 [docs/README.md](docs/README.md) 进入。第一次建议按「平台架构 → 运行时参考 → 写插件」的顺序读。

## 许可证

- engine/: AGPL-3.0
- frontend/: AGPL-3.0
- plugins/builtin/: Apache-2.0
- plugins/community/: MIT
- proto/: MIT
