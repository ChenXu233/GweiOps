# 插件 Scope 配置规范

## 概述

本文档定义了 GweiOps 插件系统的 Scope 配置规范。所有插件必须遵循此规范，确保配置的一致性和可维护性。

## Scope 设计原则

1. **统一配置源**：所有配置从 `.env` 文件读取
2. **自动分发**：核心配置系统根据 Scope 注册自动分发配置
3. **隔离性**：每个插件只能访问自己 Scope 的配置
4. **可验证**：支持配置完整性验证

## Scope 注册规范

### 命名规则

- **Scope 名称**：使用小写字母和连字符，格式为 `{类型}-{平台}-{功能}`
  - 适配器：`adapter-github-app`、`adapter-gitlab-token`、`adapter-gitlab-oauth`
  - 智能体：`agent-sensor`、`agent-diagnoser`
  - 动作：`action-k8s-scaler`
  - 仪表盘：`dashboard-main`
- **配置前缀**：使用大写字母和下划线，如 `GITHUB_APP_`、`GITLAB_TOKEN_`
- **字段名称**：使用小写字母和下划线，如 `app_id`、`private_key`

### 注册接口

```python
from engine.shared.config import config

config.register_scope(
    name="adapter-github-app",           # Scope 名称
    prefix="GITHUB_APP_",                # 环境变量前缀
    required=["app_id", "private_key"],  # 必需配置项
    optional=["webhook_secret"],         # 可选配置项
)
```

### 配置项定义

| 类型 | 说明 | 示例 |
|------|------|------|
| `required` | 启动时必须配置，否则插件无法启动 | `app_id`、`private_key` |
| `optional` | 可选配置，有默认值或功能降级 | `webhook_secret`、`timeout` |

## 配置读取规范

### 环境变量命名

配置项在 `.env` 文件中的命名规则：

```
{PREFIX}{FIELD_NAME}
```

示例：
```bash
# GitHub App Adapter
GITHUB_APP_APP_ID=your_app_id
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_APP_WEBHOOK_SECRET=your_webhook_secret
GITHUB_APP_INSTALLATION_ID=your_installation_id

# GitLab Token Adapter
GITLAB_TOKEN_URL=https://gitlab.com
GITLAB_TOKEN_TOKEN=your_token
GITLAB_TOKEN_PROJECT_ID=your_project_id

# GitLab OAuth Adapter
GITLAB_OAUTH_URL=https://gitlab.com
GITLAB_OAUTH_CLIENT_ID=your_client_id
GITLAB_OAUTH_CLIENT_SECRET=your_client_secret
```

### 配置读取

```python
from engine.shared.config import config

# 获取 Scope 配置
github_config = config.get_scope_config("adapter-github-app")

# 验证配置完整性
missing = config.validate_scope("adapter-github-app")
if missing:
    print(f"Missing config: {missing}")
```

## 插件配置类规范

每个插件应该有一个配置类，封装 Scope 的访问：

```python
# plugins/builtin/adapters/github-app/config.py
from engine.shared.config import config


class GitHubAppConfig:
    """GitHub App Adapter 配置。"""

    SCOPE_NAME = "adapter-github-app"
    SCOPE_PREFIX = "GITHUB_APP_"
    REQUIRED_FIELDS = ["app_id", "private_key"]
    OPTIONAL_FIELDS = ["webhook_secret", "installation_id"]

    def __init__(self):
        # 注册 Scope
        config.register_scope(
            name=self.SCOPE_NAME,
            prefix=self.SCOPE_PREFIX,
            required=self.REQUIRED_FIELDS,
            optional=self.OPTIONAL_FIELDS,
        )
        self._config = config.get_scope_config(self.SCOPE_NAME)

    @property
    def app_id(self) -> str:
        return self._config.get("app_id", "")

    @property
    def private_key(self) -> str:
        return self._config.get("private_key", "")

    @property
    def webhook_secret(self) -> str:
        return self._config.get("webhook_secret", "")

    @property
    def installation_id(self) -> int:
        return self._config.get("installation_id", 0)

    def validate(self) -> list[str]:
        """验证配置是否完整。"""
        return config.validate_scope(self.SCOPE_NAME)
```

## 插件启动规范

插件启动时必须：

1. **注册 Scope**：在 `__init__` 或 `on_startup` 中注册 Scope
2. **验证配置**：检查必需配置是否完整
3. **降级处理**：可选配置缺失时提供默认值或功能降级

```python
class GitHubAppAdapter(PluginBase):
    def __init__(self):
        self.config = GitHubAppConfig()
        self.client = GitHubAppClient()

    async def on_startup(self):
        """启动时验证配置。"""
        missing = self.config.validate()
        if missing:
            print(f"Warning: Missing GitHub App config: {missing}")
            # 可以选择：抛出异常、降级运行、或忽略
```

## 核心配置系统规范

核心配置系统负责：

1. **统一读取**：从 `.env` 读取所有配置
2. **Scope 注册**：管理所有插件的 Scope 注册
3. **配置分发**：根据 Scope 注册分发配置
4. **配置验证**：验证 Scope 配置完整性

```python
class ConfigManager:
    """配置管理器。"""

    def register_scope(self, name, prefix, required, optional):
        """注册配置 Scope。"""
        pass

    def get_scope_config(self, scope_name) -> dict:
        """获取指定 Scope 的配置。"""
        pass

    def validate_scope(self, scope_name) -> list[str]:
        """验证 Scope 配置是否完整。"""
        pass
```

## 最佳实践

### 1. 配置项命名

- 使用有意义的名称，避免缩写
- 使用下划线分隔单词
- 布尔值使用 `true/false`，不是 `1/0`

### 2. 敏感信息

- 私钥、Token 等敏感信息必须在 `.env` 中配置
- 不要在代码中硬编码敏感信息
- 使用 `.env.example` 作为模板，不包含真实值

### 3. 默认值

- 可选配置应该有合理的默认值
- 默认值应该在配置类中定义，不是在 `.env` 中

### 4. 错误处理

- 必需配置缺失时，插件应该抛出明确的错误信息
- 可选配置缺失时，应该有降级策略

## 示例：创建新插件配置

### 1. 创建配置类

```python
# plugins/builtin/adapters/gitlab-token/config.py
from engine.shared.config import config


class GitLabTokenConfig:
    """GitLab Token Adapter 配置。"""

    SCOPE_NAME = "adapter-gitlab-token"
    SCOPE_PREFIX = "GITLAB_TOKEN_"
    REQUIRED_FIELDS = ["url", "token"]
    OPTIONAL_FIELDS = ["project_id", "api_version"]

    def __init__(self):
        config.register_scope(
            name=self.SCOPE_NAME,
            prefix=self.SCOPE_PREFIX,
            required=self.REQUIRED_FIELDS,
            optional=self.OPTIONAL_FIELDS,
        )
        self._config = config.get_scope_config(self.SCOPE_NAME)

    @property
    def url(self) -> str:
        return self._config.get("url", "https://gitlab.com")

    @property
    def token(self) -> str:
        return self._config.get("token", "")

    @property
    def project_id(self) -> int:
        return self._config.get("project_id", 0)

    @property
    def api_version(self) -> str:
        return self._config.get("api_version", "v4")

    def validate(self) -> list[str]:
        return config.validate_scope(self.SCOPE_NAME)
```

### 2. 更新 .env.example

```bash
# GitLab Token Adapter
GITLAB_TOKEN_URL=https://gitlab.com
GITLAB_TOKEN_TOKEN=your_token
GITLAB_TOKEN_PROJECT_ID=your_project_id
GITLAB_TOKEN_API_VERSION=v4
```

### 3. 在插件中使用

```python
class GitLabTokenAdapter(PluginBase):
    def __init__(self):
        self.config = GitLabTokenConfig()

    async def on_startup(self):
        missing = self.config.validate()
        if missing:
            raise RuntimeError(f"Missing GitLab Token config: {missing}")
```

## 总结

遵循此规范可以确保：

1. **配置一致性**：所有插件使用相同的配置模式
2. **可维护性**：配置集中管理，易于理解和修改
3. **可扩展性**：新插件可以快速集成配置系统
4. **安全性**：敏感信息统一管理，不泄露到代码中
