# API 文档

## 基础 URL

```
http://localhost:8000
```

## 认证

所有 API 请求需要在 Header 中携带 GitHub App 的 JWT Token：

```
Authorization: Bearer <token>
```

## 端点

### 健康检查

```
GET /api/health
```

**响应：**

```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```

### GitHub Webhook

```
POST /webhook/github
```

**请求头：**

- `X-GitHub-Event`: 事件类型（issues, issue_comment, pull_request）
- `X-Hub-Signature-256`: Webhook 签名

**请求体：** GitHub Webhook Payload

**响应：**

```json
{
  "status": "ok",
  "event": "issues"
}
```

### 获取 Issues

```
GET /api/issues
```

**查询参数：**

- `status` (optional): Issue 状态过滤
- `limit` (optional): 返回数量限制

**响应：**

```json
[
  {
    "id": "uuid",
    "github_id": 123,
    "number": 1,
    "title": "Parser crash",
    "status": "OPEN",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### 获取分析结果

```
GET /api/issues/:id/analysis
```

**响应：**

```json
{
  "id": "uuid",
  "issue_id": "uuid",
  "report": "## Issue Analysis...",
  "patches": [
    {
      "type": "HOTFIX",
      "diff": "--- a/file.py...",
      "risk": "Low"
    }
  ],
  "status": "COMPLETED"
}
```

### 获取 Agent 会话

```
GET /api/sessions
```

**响应：**

```json
[
  {
    "id": "uuid",
    "issue_id": "uuid",
    "status": "ANALYZING",
    "started_at": "2024-01-01T00:00:00Z"
  }
]
```

### 获取项目配置

```
GET /api/config
```

**响应：**

```json
{
  "mode": "saas",
  "ai_provider": "openai",
  "ai_model": "gpt-4o",
  "min_approvals": 2,
  "owner_can_override": true
}
```

### 更新项目配置

```
PUT /api/config
```

**请求体：**

```json
{
  "mode": "saas",
  "ai_provider": "openai",
  "ai_model": "gpt-4o",
  "min_approvals": 2,
  "owner_can_override": true
}
```

**响应：** 返回更新后的配置

## 错误响应

所有错误响应格式：

```json
{
  "detail": "错误描述"
}
```

常见状态码：

- `400`: 请求参数错误
- `401`: 认证失败
- `403`: 权限不足
- `404`: 资源不存在
- `500`: 服务器内部错误
