# tests/test_metrics.py
import pytest
from src.services.metrics import MetricsCollector, GweiMetrics, metrics
from src.services.logger import StructuredLogger


def test_metrics_counter():
    collector = MetricsCollector()

    collector.increment("test_counter")
    collector.increment("test_counter")
    collector.increment("test_counter")

    assert collector.get_counter("test_counter") == 3


def test_metrics_counter_with_labels():
    collector = MetricsCollector()

    collector.increment("test_counter", {"status": "success"})
    collector.increment("test_counter", {"status": "error"})
    collector.increment("test_counter", {"status": "success"})

    assert collector.get_counter("test_counter", {"status": "success"}) == 2
    assert collector.get_counter("test_counter", {"status": "error"}) == 1


def test_metrics_gauge():
    collector = MetricsCollector()

    collector.set_gauge("test_gauge", 42.0)
    assert collector.get_gauge("test_gauge") == 42.0

    collector.set_gauge("test_gauge", 100.0)
    assert collector.get_gauge("test_gauge") == 100.0


def test_metrics_histogram():
    collector = MetricsCollector()

    collector.observe("test_histogram", 0.1)
    collector.observe("test_histogram", 0.2)
    collector.observe("test_histogram", 0.3)

    values = collector.get_histogram("test_histogram")
    assert len(values) == 3
    assert sum(values) / len(values) == pytest.approx(0.2)


def test_gwei_metrics():
    # 使用全局 metrics 实例，因为 GweiMetrics 使用全局实例
    # 先重置全局实例的状态（通过创建新的来避免污染）
    import src.services.metrics as m
    m.metrics = MetricsCollector()
    collector = m.metrics

    # 记录 Issue 处理
    GweiMetrics.record_issue_processed("success")
    GweiMetrics.record_issue_processed("success")
    GweiMetrics.record_issue_processed("error")

    # 记录 PR 创建
    GweiMetrics.record_pr_created()

    # 记录 LLM 调用
    GweiMetrics.record_llm_call(1.5, "gpt-4o")
    GweiMetrics.record_llm_call(2.0, "gpt-4o")

    # 记录投票
    GweiMetrics.record_vote("pr-1", "approve")
    GweiMetrics.record_vote("pr-1", "reject")

    # 设置活跃会话
    GweiMetrics.set_active_sessions(5)

    # 验证指标
    assert collector.get_counter("gwei_issues_processed_total", {"status": "success"}) == 2
    assert collector.get_counter("gwei_prs_created_total") == 1
    assert len(collector.get_histogram("gwei_llm_call_duration_seconds", {"model": "gpt-4o"})) == 2
    assert collector.get_gauge("gwei_active_sessions") == 5


def test_logger():
    logger = StructuredLogger("test")

    # 测试不同级别的日志
    logger.info("Test info message", user_id=123)
    logger.warning("Test warning message", action="test")
    logger.error("Test error message", error="test error")
    logger.debug("Test debug message")

    # 没有异常即为成功
    assert True


def test_metrics_get_all():
    collector = MetricsCollector()

    collector.increment("counter1")
    collector.set_gauge("gauge1", 42.0)
    collector.observe("histogram1", 0.1)

    metrics = collector.get_metrics()
    assert len(metrics) == 3
