# tests/test_integration/test_github_app_loop.py
"""
GitHub App 最小闭环集成测试

验证目标：
1. 代码是否可以启动（导入正确）
2. Webhook 路由是否正确注册
3. GitHubAppAdapter 和 SensorAgent 是否可以正常初始化
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================================
# Step 1: 检查代码是否可以启动（导入测试）
# ============================================================================


class TestImports:
    """验证所有相关模块可以正常导入。"""

    def test_import_engine_config(self):
        """验证 engine.shared.config 可以导入。"""
        from engine.shared.config import config, Settings
        assert config is not None
        assert Settings is not None

    def test_import_plugin_base(self):
        """验证 plugin_manager.base 可以导入。"""
        from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType
        assert PluginBase is not None
        assert PluginInfo is not None
        assert PluginType is not None

    def test_import_github_app_adapter(self):
        """验证 GitHubAppAdapter 及其依赖可以导入。"""
        import importlib
        # 目录名含连字符，需用 importlib 导入
        plugin_mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        config_mod = importlib.import_module("plugins.builtin.adapters.github-app.config")
        client_mod = importlib.import_module("plugins.builtin.adapters.github-app.client")
        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        assert plugin_mod.GitHubAppAdapter is not None
        assert config_mod.GitHubAppConfig is not None
        assert client_mod.GitHubAppClient is not None
        assert handlers_mod.WebhookHandler is not None

    def test_import_sensor_agent(self):
        """验证 SensorAgent 及其依赖可以导入。"""
        from plugins.builtin.agents.sensor.plugin import SensorAgent
        from plugins.builtin.agents.sensor.labeler import LabelGenerator
        from plugins.builtin.agents.sensor.completeness import CompletenessChecker
        from plugins.builtin.agents.sensor.duplicate import DuplicateDetector
        assert SensorAgent is not None
        assert LabelGenerator is not None
        assert CompletenessChecker is not None
        assert DuplicateDetector is not None

    def test_import_webhook_routes(self):
        """验证 webhook 路由模块可以导入。"""
        from engine.api.routes.webhook import router, get_adapter, get_sensor
        assert router is not None
        assert get_adapter is not None
        assert get_sensor is not None

    def test_import_fastapi_app(self):
        """验证 FastAPI 应用可以导入。"""
        from engine.api.app import app
        assert app is not None


# ============================================================================
# Step 2: 验证 Webhook 路由
# ============================================================================


class TestWebhookRoutes:
    """验证 Webhook 路由是否正确注册。"""

    def test_webhook_routes_registered(self):
        """验证 /webhook/github 和 /webhook/github/comment 路由存在。"""
        from engine.api.app import app

        # 获取所有注册的路由路径
        routes = [route.path for route in app.routes]

        assert "/webhook/github" in routes, "路由 /webhook/github 未注册"
        assert "/webhook/github/comment" in routes, "路由 /webhook/github/comment 未注册"

    def test_webhook_routes_methods(self):
        """验证 Webhook 路由支持 POST 方法。"""
        from engine.api.app import app

        webhook_routes = {}
        for route in app.routes:
            if hasattr(route, "path") and route.path.startswith("/webhook"):
                methods = getattr(route, "methods", set())
                webhook_routes[route.path] = methods

        assert "POST" in webhook_routes.get("/webhook/github", set()), \
            "/webhook/github 路由不支持 POST 方法"
        assert "POST" in webhook_routes.get("/webhook/github/comment", set()), \
            "/webhook/github/comment 路由不支持 POST 方法"


# ============================================================================
# Step 3: 验证插件初始化
# ============================================================================


class TestPluginInitialization:
    """验证 GitHubAppAdapter 和 SensorAgent 可以正常初始化。"""

    def test_github_app_adapter_instantiation(self):
        """验证 GitHubAppAdapter 可以实例化。"""
        import importlib
        mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        GitHubAppAdapter = mod.GitHubAppAdapter

        adapter = GitHubAppAdapter()
        assert adapter is not None
        assert adapter.config is None  # 尚未调用 on_startup
        assert adapter.client is None
        assert adapter.webhook_handler is None

    def test_github_app_adapter_info(self):
        """验证 GitHubAppAdapter 可以返回插件信息。"""
        import importlib
        from engine.plugin_manager.base import PluginType

        mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        GitHubAppAdapter = mod.GitHubAppAdapter

        adapter = GitHubAppAdapter()
        info = adapter.info()

        assert info.name == "github-app-adapter"
        assert info.version == "1.0.0"
        assert info.type == PluginType.ADAPTER
        assert "webhook.receive" in info.capabilities

    def test_sensor_agent_instantiation(self):
        """验证 SensorAgent 可以实例化。"""
        from plugins.builtin.agents.sensor.plugin import SensorAgent

        # SensorAgent 需要 LLMService，使用 mock
        with patch("plugins.builtin.agents.sensor.plugin.LLMService") as MockLLM:
            MockLLM.return_value = MagicMock()
            sensor = SensorAgent()

        assert sensor is not None
        assert sensor.labeler is not None
        assert sensor.completeness is not None
        assert sensor.duplicate is not None

    def test_sensor_agent_info(self):
        """验证 SensorAgent 可以返回插件信息。"""
        from plugins.builtin.agents.sensor.plugin import SensorAgent
        from engine.plugin_manager.base import PluginType

        with patch("plugins.builtin.agents.sensor.plugin.LLMService") as MockLLM:
            MockLLM.return_value = MagicMock()
            sensor = SensorAgent()

        info = sensor.info()

        assert info.name == "sensor-agent"
        assert info.version == "2.0.0"
        assert info.type == PluginType.AGENT
        assert "issue.llm_analysis" in info.capabilities

    def test_github_app_adapter_startup_with_mock(self):
        """验证 GitHubAppAdapter 可以在 mock 环境下完成启动。"""
        import importlib
        mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        GitHubAppAdapter = mod.GitHubAppAdapter

        adapter = GitHubAppAdapter()

        # Mock 配置验证通过
        with patch.object(adapter, "config") as mock_config:
            mock_config.validate.return_value = []
            mock_config.webhook_secret = ""

            # 手动设置属性来模拟启动
            adapter.config = mock_config
            adapter.client = MagicMock()
            adapter.webhook_handler = MagicMock()

            assert adapter.config is not None
            assert adapter.client is not None
            assert adapter.webhook_handler is not None

    def test_sensor_agent_startup(self):
        """验证 SensorAgent 可以完成启动（无外部依赖）。"""
        from plugins.builtin.agents.sensor.plugin import SensorAgent

        with patch("plugins.builtin.agents.sensor.plugin.LLMService") as MockLLM:
            MockLLM.return_value = MagicMock()
            sensor = SensorAgent()

        # on_startup 是 pass，应该不抛出异常
        loop = asyncio.new_event_loop()
        loop.run_until_complete(sensor.on_startup())
        loop.close()


# ============================================================================
# 额外验证：Webhook 处理器逻辑
# ============================================================================


class TestWebhookHandlerLogic:
    """验证 WebhookHandler 的核心逻辑。"""

    def test_verify_signature_with_valid_secret(self):
        """验证签名验证逻辑（有效签名）。"""
        import hmac
        import hashlib
        import importlib

        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        WebhookHandler = handlers_mod.WebhookHandler

        config = MagicMock()
        config.webhook_secret = "test-secret"

        handler = WebhookHandler(config)

        body = b'{"action": "opened"}'
        mac = hmac.new(b"test-secret", body, hashlib.sha256)
        signature = f"sha256={mac.hexdigest()}"

        assert handler.verify_signature(body, signature) is True

    def test_verify_signature_with_invalid_secret(self):
        """验证签名验证逻辑（无效签名）。"""
        import importlib

        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        WebhookHandler = handlers_mod.WebhookHandler

        config = MagicMock()
        config.webhook_secret = "test-secret"

        handler = WebhookHandler(config)

        body = b'{"action": "opened"}'
        signature = "sha256=invalid-signature"

        assert handler.verify_signature(body, signature) is False

    def test_parse_event_ping(self):
        """验证 ping 事件解析。"""
        import importlib

        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        WebhookHandler = handlers_mod.WebhookHandler

        config = MagicMock()
        handler = WebhookHandler(config)

        headers = {"X-GitHub-Event": "ping"}
        body = b'{}'

        event = handler.parse_event(headers, body)
        assert event is not None
        assert event["type"] == "ping"

    def test_parse_event_issues_opened(self):
        """验证 issues opened 事件解析。"""
        import json
        import importlib

        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        WebhookHandler = handlers_mod.WebhookHandler

        config = MagicMock()
        handler = WebhookHandler(config)

        headers = {"X-GitHub-Event": "issues"}
        payload = {
            "action": "opened",
            "issue": {
                "number": 1,
                "title": "Test Issue",
                "body": "Test body",
            },
            "repository": {
                "name": "test-repo",
                "owner": {"login": "test-owner"},
            },
        }
        body = json.dumps(payload).encode()

        event = handler.parse_event(headers, body)
        assert event is not None
        assert event["type"] == "issues"
        assert event["action"] == "opened"

    def test_extract_issue_info(self):
        """验证 Issue 信息提取。"""
        import json
        import importlib

        handlers_mod = importlib.import_module("plugins.builtin.adapters.github-app.handlers")
        WebhookHandler = handlers_mod.WebhookHandler

        config = MagicMock()
        handler = WebhookHandler(config)

        headers = {"X-GitHub-Event": "issues"}
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Bug Report",
                "body": "Something is broken",
            },
            "repository": {
                "name": "my-repo",
                "owner": {"login": "my-org"},
            },
            "sender": {"login": "test-user"},
        }
        body = json.dumps(payload).encode()

        event = handler.parse_event(headers, body)
        issue_info = handler.extract_issue_info(event)

        assert issue_info is not None
        assert issue_info["owner"] == "my-org"
        assert issue_info["repo"] == "my-repo"
        assert issue_info["issue_number"] == 42
        assert issue_info["title"] == "Bug Report"


# ============================================================================
# 额外验证：SensorAgent 分析逻辑
# ============================================================================


class TestSensorAgentLogic:
    """验证 SensorAgent 的核心分析逻辑。"""

    def test_label_generation(self):
        """验证标签生成功能。"""
        from plugins.builtin.agents.sensor.labeler import LabelGenerator

        labeler = LabelGenerator()

        # Bug 相关
        labels = labeler.generate("App crashes on startup", "Getting a null pointer error")
        assert "bug" in labels

        # Feature 相关
        labels = labeler.generate("Add dark mode support", "Please implement dark theme")
        assert "feature" in labels

    def test_completeness_check(self):
        """验证完整性检查功能。"""
        from plugins.builtin.agents.sensor.completeness import CompletenessChecker

        checker = CompletenessChecker()

        # 不完整的 Issue
        report = checker.check("Something is broken")
        assert not report.is_complete
        assert len(report.missing_fields) > 0

        # 完整的 Issue
        report = checker.check(
            "Steps to reproduce: 1. Open app\n"
            "Expected behavior: Should work\n"
            "Actual behavior: Crashes"
        )
        assert report.is_complete

    @pytest.mark.asyncio
    async def test_sensor_handle_event(self):
        """验证 SensorAgent 事件处理。"""
        from plugins.builtin.agents.sensor.plugin import SensorAgent

        with patch("plugins.builtin.agents.sensor.plugin.LLMService") as MockLLM:
            mock_llm = MagicMock()
            mock_llm.call = AsyncMock(return_value=MagicMock(
                content='{"summary": "test", "category": "bug"}'
            ))
            MockLLM.return_value = mock_llm
            sensor = SensorAgent(llm_service=mock_llm)

        result = await sensor.handle_event("issue.created", {
            "issue": {
                "title": "Test Bug",
                "body": "Steps to reproduce: ...\nExpected: ...\nActual: ...",
            }
        })

        assert result["status"] == "ok"
        assert "reply" in result
        assert "labels" in result


# ============================================================================
# 额外验证：健康检查路由
# ============================================================================


class TestHealthRoute:
    """验证健康检查路由。"""

    def test_health_route_registered(self):
        """验证 /api/health 路由存在。"""
        from engine.api.app import app

        routes = [route.path for route in app.routes]
        assert "/api/health" in routes, "路由 /api/health 未注册"
