# 既未 · Gwei /ˈdʒiː.weɪ/ 设计文档

> AI 负责完成，人类负责决定。

**文档版本**：v1.0  
**最后更新**：2026-06-17  
**作者**：Gwei Team

---

## 目录

1. [项目概述](#1-项目概述)
2. [核心架构](#2-核心架构)
3. [Agent 会话设计](#3-agent-会话设计)
4. [数据模型](#4-数据模型)
5. [错误处理和边界情况](#5-错误处理和边界情况)
6. [测试策略](#6-测试策略)
7. [部署和配置](#7-部署和配置)
8. [定价策略](#8-定价策略)
9. [技术栈](#9-技术栈)

---

## 1. 项目概述

### 1.1 项目背景

在开源项目维护中，开发者面临以下痛点：

- **Issue 处理耗时**：手动分类、打标签、检测重复
- **Bug 复现困难**：需要手动搭建环境、复现问题
- **修复方案单一**：通常只有一种修复思路
- **PR 流程繁琐**：代码审查、冲突解决、测试

### 1.2 项目定位

**既未 · Gwei** 是一个 AI 驱动的 GitHub Issue 自动修复平台，核心理念是：

> AI 负责完成，人类负责决定。

《易经》以"既济"收束，以"未济"终篇。合在一起，只讲一件事：完成从来不是终点。

Gwei 深谙此道。它替你扛下繁重的那部分——分析 Issue、复现 Bug、生成三种修复方案——然后精准地停在 **你必须做决定** 的那个节点。你来选路，它陪你走，从 Issue 到 PR，一轮又一轮。

因为最好的 AI，从不替代你。它成全你。

### 1.3 核心目标

1. **团队协作平台**：自动化 Issue 分类、PR 流程
2. **开源项目维护助手**：处理大量 Issue，减轻维护者负担

### 1.4 核心价值

- **完整闭环**：从 Issue 到 PR 合并，全流程自动化
- **人类决策点**：所有代码修改需要人类确认
- **动态流程**：根据 Issue 类型选择不同处理流程

---

## 2. 核心架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub App                            │
│  • Webhook 接收                                          │
│  • Issue/PR 事件处理                                      │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  Webhook 处理器                          │
│  • 接收 GitHub 事件                                      │
│  • 解析 Issue 内容                                        │
│  • 创建独立会话                                           │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Issue #1   │  │   Issue #2   │  │   Issue #3   │
│   Agent 会话  │  │   Agent 会话  │  │   Agent 会话  │
│              │  │              │  │              │
│ • 状态机     │  │ • 状态机     │  │ • 状态机     │
│ • 工具集     │  │ • 工具集     │  │ • 工具集     │
│ • 决策引擎   │  │ • 决策引擎   │  │ • 决策引擎   │
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                    共享资源                               │
│  • GitHub API（限流管理）                                │
│  • LLM API（配额管理）                                   │
│  • 数据库连接池                                           │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 职责 |
|------|------|
| **GitHub App 服务** | 接收 Webhook 事件，管理 GitHub API 调用 |
| **Agent 调度器** | 接收 Webhook 事件，创建独立 Agent 会话 |
| **Agent 会话（LangGraph）** | 状态机、工具集、决策引擎 |
| **数据层** | PostgreSQL、pgvector、Redis |

### 2.3 数据流

```
GitHub Issue → Webhook → 调度器 → Agent 会话 → GitHub API → PR
```

---

## 3. Agent 会话设计

### 3.1 会话状态机

```
INIT → ANALYZING → REPRODUCING → GENERATING → WAITING → CREATING_PR → DONE
```

### 3.2 状态职责

| 状态 | 职责 | 工具 |
|------|------|------|
| **INIT** | 初始化会话，加载配置 | - |
| **ANALYZING** | 分析 Issue，判断类型 | LLM、GitHub API |
| **REPRODUCING** | 复现 Bug（如果是 Bug） | Git、Shell、Docker |
| **GENERATING** | 生成三种 Patch 方案 | LLM、代码分析 |
| **WAITING** | 等待用户选择方案 | GitHub API（评论） |
| **CREATING_PR** | 创建 PR | Git、GitHub API |
| **DONE** | 会话结束，释放资源 | - |

### 3.3 动态流程选择

Agent 根据 Issue 类型，选择不同的处理流程：

| Issue 类型 | 流程 |
|-----------|------|
| **Bug 报告** | 分析 → 复现 → 定位 → 生成 Patch → PR |
| **功能请求** | 分析 → 评估 → 设计 → 实现 → PR |
| **文档问题** | 分析 → 修改文档 → PR |
| **重复 Issue** | 分析 → 标记重复 → 关闭 |
| **问题咨询** | 分析 → 回答问题 → 关闭 |
| **无法处理** | 分析 → 通知用户 → 关闭 |

### 3.4 工具集

| 工具 | 功能 |
|------|------|
| **GitHub API** | Issue/PR 操作、评论、标签 |
| **Git 工具** | clone、checkout、commit、push |
| **代码分析** | AST 解析、代码搜索、堆栈分析 |
| **LLM 调用** | Issue 分析、Patch 生成 |
| **测试执行** | 运行测试用例 |

### 3.5 人类决策点

**核心原则**：
1. 所有涉及修改代码的，先给方案
2. 开发者主动发起才能开始实现
3. PR 流程多轮实现

**方案展示格式**：

```markdown
## 🛠️ 修复方案

### 方案 A：快速修复（Hotfix）
- **改动**：最小改动，快速解决
- **风险**：低
- **适用**：紧急修复

### 方案 B：源头修复（Proper Fix）
- **改动**：根本原因修复
- **风险**：中
- **适用**：推荐方案

### 方案 C：重构修复（Refactor）
- **改动**：代码重构
- **风险**：高
- **适用**：长期维护

请回复选择方案（A/B/C），或提出修改建议。
```

### 3.6 双向审核机制

**核心原则**：
1. AI 审核协作者 PR
2. AI 的修改需要协作者同意
3. 双向审核：AI 审核人类代码，人类审核 AI 代码

**PR 分析流程**：

```
PR 提交（AI 或人类）
    │
    ▼
┌─────────────────┐
│  分析修改范围    │ ← 自动分析
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  判断修改类型    │
│  • 核心逻辑      │
│  • 配置文件      │
│  • 文档          │
│  • 测试          │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  计算风险分数    │ ← 0-100 分
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  确定投票阈值    │ ← 根据风险分数
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  请求投票        │
└─────────────────┘
```

### 3.7 协作者权限区分

| 角色 | 权限 | 意见权重 |
|------|------|---------|
| **Owner** | 完全控制 | 最高 |
| **Collaborator** | 代码修改、Issue 管理 | 高 |
| **Contributor** | 评论、建议 | 中 |
| **Others** | 评论 | 低 |

### 3.8 重大更改投票机制

**重大更改定义**：

| 更改类型 | 是否重大 | 说明 |
|---------|---------|------|
| **修改核心逻辑** | ✅ 是 | 影响主要功能 |
| **删除文件/代码** | ✅ 是 | 可能破坏功能 |
| **修改配置** | ✅ 是 | 影响运行行为 |
| **添加依赖** | ⚠️ 可能 | 需要评估安全性 |
| **修改文档** | ❌ 否 | 影响较小 |
| **修复 Bug** | ❌ 否 | 通常是安全的 |

**投票阈值**：

| 风险分数 | 投票阈值 | 说明 |
|---------|---------|------|
| **0-29** | 1 人 | 低风险，1 人同意即可 |
| **30-59** | 2 人 | 中风险，需要 2 人同意 |
| **60-100** | 3 人 | 高风险，需要 3 人同意 |

---

## 4. 数据模型

### 4.1 核心表结构

```sql
-- 项目表
CREATE TABLE projects (
    id UUID PRIMARY KEY,
    github_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    config JSONB,  -- 用户配置（API Key、模型选择等）
    created_at TIMESTAMP DEFAULT NOW()
);

-- Issue 表
CREATE TABLE issues (
    id UUID PRIMARY KEY,
    github_id INTEGER NOT NULL,
    project_id UUID REFERENCES projects(id),
    number INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    body TEXT,
    labels TEXT[],
    embedding VECTOR(1536),  -- 向量搜索用
    status VARCHAR(50) DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(project_id, github_id)
);

-- Agent 会话表
CREATE TABLE agent_sessions (
    id UUID PRIMARY KEY,
    issue_id UUID REFERENCES issues(id),
    status VARCHAR(50) NOT NULL,  -- INIT, ANALYZING, etc.
    state JSONB,  -- 当前状态数据
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP
);

-- Patch 方案表
CREATE TABLE patches (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES agent_sessions(id),
    type VARCHAR(50) NOT NULL,  -- HOTFIX, PROPER, REFACTOR
    diff TEXT NOT NULL,
    risk_assessment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- PR 表
CREATE TABLE pull_requests (
    id UUID PRIMARY KEY,
    patch_id UUID REFERENCES patches(id),
    github_id INTEGER,
    number INTEGER,
    url VARCHAR(255),
    status VARCHAR(50) DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 投票记录表
CREATE TABLE approval_votes (
    id UUID PRIMARY KEY,
    pr_id UUID REFERENCES pull_requests(id),
    voter_id INTEGER NOT NULL,  -- GitHub 用户 ID
    voter_role VARCHAR(50) NOT NULL,  -- owner, collaborator
    vote VARCHAR(50) NOT NULL,  -- approve, reject, comment
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pr_id, voter_id)
);
```

### 4.2 状态枚举

```sql
CREATE TYPE issue_status AS ENUM (
    'OPEN', 'ANALYZING', 'HAS_PATCH', 'PR_CREATED', 'FIXED', 'CLOSED'
);

CREATE TYPE session_status AS ENUM (
    'INIT', 'ANALYZING', 'REPRODUCING', 'GENERATING', 
    'WAITING', 'CREATING_PR', 'DONE', 'FAILED'
);

CREATE TYPE patch_type AS ENUM (
    'HOTFIX', 'PROPER', 'REFACTOR'
);
```

---

## 5. 错误处理和边界情况

### 5.1 Agent 会话错误处理

| 错误场景 | 处理策略 |
|---------|---------|
| **LLM API 调用失败** | 重试 3 次，间隔指数退避 |
| **GitHub API 限流** | 等待后重试，记录限流状态 |
| **Bug 复现失败** | 跳过复现，直接进入分析 |
| **Patch 生成失败** | 降级为单一方案，或请求人工介入 |
| **Git 操作失败** | 回滚到上一个稳定状态 |
| **会话超时** | 自动结束会话，通知用户 |

### 5.2 边界情况处理

| 场景 | 处理策略 |
|------|---------|
| **Issue 非 Bug** | 跳过复现，直接分析需求 |
| **Issue 描述不清** | 评论请求补充信息，暂停会话 |
| **重复 Issue** | 标记为重复，关闭会话 |
| **用户无响应** | 7 天后自动关闭会话 |
| **PR 冲突** | 自动 rebase，或通知用户 |

### 5.3 用户干预点

```
Agent 遇到问题 → 评论 Issue 请求帮助 → 暂停会话
                ↓
用户回复 → 恢复会话 → 继续处理
```

---

## 6. 测试策略

### 6.1 测试层次

| 层次 | 测试内容 | 工具 |
|------|---------|------|
| **单元测试** | 单个函数、类 | pytest |
| **集成测试** | Agent 会话、工具调用 | pytest + mock |
| **端到端测试** | 完整 Issue → PR 流程 | GitHub API + 测试仓库 |
| **性能测试** | 并发会话、响应时间 | locust |

### 6.2 Agent 会话测试

```python
# 测试 Bug 处理流程
def test_bug_fix_flow():
    # 创建测试 Issue
    issue = create_test_issue("bug", "Parser crash on empty input")
    
    # 创建 Agent 会话
    session = AgentSession(issue)
    
    # 执行流程
    session.run()
    
    # 验证结果
    assert session.status == "DONE"
    assert session.pr_created == True
    assert len(session.patches) == 3  # 三种方案
```

### 6.3 集成测试场景

| 场景 | 测试内容 |
|------|---------|
| **Bug 修复** | Issue → 分析 → 复现 → Patch → PR |
| **功能请求** | Issue → 分析 → 设计 → 实现 → PR |
| **重复检测** | Issue → 分析 → 标记重复 |
| **投票流程** | PR → 分析 → 投票 → 合并 |
| **错误处理** | API 失败 → 重试 → 降级 |

---

## 7. 部署和配置

### 7.1 双模部署架构

```
┌─────────────────────────────────────────────────────────┐
│                    双模部署                               │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              SaaS 模式                           │    │
│  │  • 用户不需要自己部署                             │    │
│  │  • 我们提供托管服务                               │    │
│  │  • 我们提供 AI 模型                               │    │
│  │  • 用户不需要 API Key                             │    │
│  │  • 按使用量付费                                   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              自托管模式                           │    │
│  │  • 用户自己部署                                   │    │
│  │  • 用户自己配置 AI 模型                           │    │
│  │  • 用户自己管理 API Key                           │    │
│  │  • 完全控制                                       │    │
│  │  • 免费                                           │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 7.2 用户注册流程

```
用户在 GitHub Marketplace
    │
    ▼
安装 Gwei GitHub App
    │
    ▼
选择托管模式
    │
    ├─ 默认：SaaS 模式
    │   • 用户不需要配置
    │   • 直接使用
    │   • 按使用量付费
    │
    └─ 可选：自托管模式
        • 用户自己部署
        • 用户自己配置 AI
        • 免费
    │
    ▼
开始使用
```

### 7.3 用户配置文件

```yaml
# .github/gwei.yml
# SaaS 模式（默认）
mode: saas
# 不需要配置 AI 相关内容

# 自托管模式
# mode: self-hosted
# ai:
#   provider: openai
#   api_key: ${OPENAI_API_KEY}
#   model: gpt-4
```

### 7.4 资源需求（自托管）

| 资源 | 最低配置 | 推荐配置 |
|------|---------|---------|
| **CPU** | 2 核 | 4 核 |
| **内存** | 4 GB | 8 GB |
| **存储** | 20 GB | 50 GB |
| **网络** | 10 Mbps | 50 Mbps |

---

## 8. 定价策略

### 8.1 按次收费逻辑

| 概念 | 说明 |
|------|------|
| **AI 调用次数** | 每个 Issue 的 AI 调用次数 |
| **免费次数** | 套餐包含的免费调用次数 |
| **超出费用** | 超出后按次收费 |

### 8.2 每个 Issue 的 AI 调用次数

| 调用类型 | 次数 | 说明 |
|---------|------|------|
| **Issue 分析** | 1 次 | 分析 Issue 类型 |
| **代码分析** | 3-5 次 | 分析代码结构 |
| **Bug 复现** | 2-3 次 | 复现 Bug |
| **Patch 生成** | 3-5 次 | 生成修复方案 |
| **PR 描述** | 1 次 | 生成 PR 描述 |
| **多轮迭代** | 5-10 次 | PR 流程中的迭代 |
| **总计** | 15-25 次 | 每个 Issue 平均 |

### 8.3 定价表

| 套餐 | 月费 | Issue 配额 | 免费 AI 调用 | 超出费用 |
|------|------|-----------|-------------|---------|
| **免费** | $0 | 10 个（试用） + 1 个/月 | 50 次/月 | $0.50/次 |
| **基础** | $49/月 | 100 个/月 | 500 次/月 | $0.40/次 |
| **专业** | $149/月 | 500 个/月 | 2500 次/月 | $0.30/次 |
| **Ultra** | $299/月 | 1000 个/月 | 5000 次/月 | $0.20/次 |
| **无尽版** | $799/月 | 无限制 | 10000 次/月 | $0.15/次 |

### 8.4 用户账单示例

```
用户账单（基础套餐）
    │
    ├─ 月费：$49
    │
    ├─ 免费 AI 调用：500 次/月
    │
    └─ AI 使用情况：
        • Issue #1：20 次 ✓
        • Issue #2：25 次 ✓
        • Issue #3：18 次 ✓
        • ...
        • 总计：600 次
        • 超出：100 次
        • 超出费用：100 × $0.40 = $40.00
    
    总计：$89.00
```

---

## 9. 技术栈

### 9.1 后端

| 组件 | 技术 | 理由 |
|------|------|------|
| **Agent 框架** | LangGraph | 状态机、动态路由、Python 原生 |
| **Web 框架** | FastAPI | 异步、类型安全、文档自动生成 |
| **ORM** | SQLAlchemy 2.0 | 成熟、异步支持、类型安全 |
| **数据库** | PostgreSQL + pgvector | 向量搜索 + 关系数据 |
| **缓存** | Redis | 任务队列、会话缓存 |
| **任务队列** | Celery | 异步任务处理 |

### 9.2 AI/LLM

| 组件 | 技术 | 理由 |
|------|------|------|
| **LLM** | OpenAI API / Claude API | 用户现有中转站 |
| **Embedding** | OpenAI Ada | 向量搜索成熟 |
| **向量数据库** | pgvector | 轻量、易部署 |

### 9.3 工具执行

| 组件 | 技术 | 理由 |
|------|------|------|
| **容器化** | Docker | 安全隔离、环境一致 |
| **编排** | Docker Compose | 本地开发、测试 |

---

## 附录

### A. 配置文件示例

```yaml
# .github/gwei.yml

# 托管模式
mode: saas  # saas or self-hosted

# AI 配置（自托管模式）
ai:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4
  temperature: 0.7

# 投票配置
approval:
  min_approvals: 2
  owner_can_override: true
  timeout_hours: 72

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

# PR 配置
pull_request:
  auto_create: true
  reviewers:
    - "@maintainer1"
    - "@maintainer2"
```

### B. API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/webhook/github` | POST | GitHub Webhook 接收 |
| `/api/projects` | GET/POST | 项目管理 |
| `/api/projects/:id/config` | GET/PUT | 项目配置 |
| `/api/issues` | GET | Issue 列表 |
| `/api/issues/:id/analysis` | GET | 分析结果 |
| `/api/health` | GET | 健康检查 |

### C. 状态标签体系

| 标签 | 说明 | 时机 |
|------|------|------|
| `bug` | Bug 报告 | Issue 创建时 |
| `duplicate` | 重复 Issue | 重复度>80% |
| `needs-analysis` | 需要分析 | 重复度≤80% |
| `analyzed` | 已分析 | 分析完成 |
| `has-patch` | 有修复方案 | Patch 指南生成 |
| `patch-selected` | 方案已选择 | 开发者勾选后 |
| `pr-created` | PR 已创建 | PR 创建后 |
| `ai-generated` | AI 生成 | PR 创建时 |
| `needs-review` | 需要 review | PR 创建时 |
| `fixed` | 已修复 | PR 合并后 |
