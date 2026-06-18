# 既未 · Gwei

> AI 负责完成，人类负责决定。

**既未 · Gwei** 是一个 AI 驱动的 GitHub Issue 修复平台。

《易经》以"既济"收束，以"未济"终篇。合在一起，只讲一件事：完成从来不是终点。

Gwei 深谙此道。它替你扛下繁重的那部分——分析 Issue、复现 Bug、生成三种修复方案——然后精准地停在 **你必须做决定** 的那个节点。你来选路，它陪你走，从 Issue 到 PR，一轮又一轮。

因为最好的 AI，从不替代你。它成全你。

## 功能特性

- 🏷️ **自动标签生成**：根据 Issue 内容自动生成标签
- 🔍 **重复检测**：智能检测重复 Issue
- ✅ **完整性验证**：验证 Issue 信息是否完整
- 🛠️ **三种修复方案**：生成快速修复、源头修复、重构修复三种方案
- 📝 **PR 自动化**：自动创建 PR，处理投票和审查
- 🔍 **代码审查**：AI 驱动的代码质量检查

## 快速开始

### 前置要求

- Python 3.12+
- Node.js 18+
- PostgreSQL 16+ (with pgvector)
- Redis 7+

### 使用 Docker

```bash
# 克隆仓库
git clone https://github.com/your-org/gwei.git
cd gwei

# 复制环境变量
cp .env.example .env

# 编辑 .env 文件，填入你的配置
# vim .env

# 启动服务
docker-compose up -d
```

### 手动安装

#### 后端

```bash
cd gwei

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .

# 运行数据库迁移
alembic upgrade head

# 启动服务
uvicorn src.main:app --reload
```

#### 前端

```bash
cd gwei/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql+asyncpg://gwei:gwei@localhost:5432/gwei` |
| `REDIS_URL` | Redis 连接字符串 | `redis://localhost:6379/0` |
| `GITHUB_APP_ID` | GitHub App ID | - |
| `GITHUB_PRIVATE_KEY` | GitHub App 私钥 | - |
| `GITHUB_WEBHOOK_SECRET` | GitHub Webhook 密钥 | - |
| `LLM_PROVIDER` | LLM 提供商 | `openai` |
| `LLM_API_KEY` | LLM API 密钥 | - |
| `LLM_MODEL` | LLM 模型 | `gpt-4o` |

### 项目配置

在项目根目录创建 `.github/gwei.yml`：

```yaml
# 托管模式
mode: saas  # saas or self-hosted

# 投票配置
approval:
  min_approvals: 2
  owner_can_override: true

# 核心文件定义
core_files:
  - src/parser/**
  - src/lexer/**
  - src/type_checker/**

# 标签映射
labels:
  auto: true
  mapping:
    lexer: ["lexer", "token", "scan"]
    parser: ["parser", "ast", "syntax"]
```

## 使用方法

1. 安装 GitHub App 到你的仓库
2. 创建 Issue
3. Gwei 会自动分析 Issue 并生成修复方案
4. 在 Issue 评论中选择方案（A/B/C）
5. Gwei 自动创建 PR
6. 协作者投票批准 PR
7. PR 合并

## 定价

| 套餐 | 月费 | Issue 配额 | AI 调用 | 超出费用 |
|------|------|-----------|---------|---------|
| **免费** | $0 | 10 个（试用） + 1 个/月 | 50 次/月 | $0.50/次 |
| **基础** | $49/月 | 100 个/月 | 500 次/月 | $0.40/次 |
| **专业** | $149/月 | 500 个/月 | 2500 次/月 | $0.30/次 |
| **Ultra** | $299/月 | 1000 个/月 | 5000 次/月 | $0.20/次 |
| **无尽版** | $799/月 | 无限制 | 10000 次/月 | $0.15/次 |

## 开发

### 运行测试

```bash
cd gwei
pytest tests/ -v
```

### 项目结构

```
gwei/
├── src/
│   ├── main.py          # FastAPI 入口
│   ├── config.py         # 配置管理
│   ├── db/               # 数据库
│   ├── models/           # 数据模型
│   ├── agent/            # LangGraph Agent
│   ├── api/              # API 路由
│   └── services/         # 业务服务
├── tests/                # 测试
├── frontend/             # Next.js 前端
├── Dockerfile            # Docker 配置
├── docker-compose.yml    # Docker Compose
└── pyproject.toml        # Python 项目配置
```

## 许可证

Apache 2.0
