# src/services/metrics.py
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict


@dataclass
class Metric:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MetricsCollector:
    """指标收集器。"""

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._metrics: list[Metric] = []

    def increment(self, name: str, labels: dict[str, str] | None = None):
        """增加计数器。"""
        key = self._make_key(name, labels)
        self._counters[key] += 1

        self._metrics.append(Metric(
            name=name,
            value=self._counters[key],
            labels=labels or {},
        ))

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """设置仪表盘值。"""
        key = self._make_key(name, labels)
        self._gauges[key] = value

        self._metrics.append(Metric(
            name=name,
            value=value,
            labels=labels or {},
        ))

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None):
        """记录直方图观测值。"""
        key = self._make_key(name, labels)
        self._histograms[key].append(value)

        self._metrics.append(Metric(
            name=name,
            value=value,
            labels=labels or {},
        ))

    def snapshot(self, prefix: str | None = None) -> list[Metric]:
        """当前各时间序列的最新值(按 name+labels 去重,可按名称前缀过滤)。"""
        latest: dict[tuple[str, tuple[tuple[str, str], ...]], Metric] = {}
        for m in self._metrics:
            if prefix and not m.name.startswith(prefix):
                continue
            key = (m.name, tuple(sorted(m.labels.items())))
            latest[key] = m
        return list(latest.values())

    def sum_metric(self, name: str, labels: dict[str, str] | None = None) -> float:
        """汇总同名(且匹配给定标签)序列的当前值;计数器语义下即总增量。"""
        total = 0.0
        for m in self.snapshot(prefix=name):
            if m.name != name:
                continue
            if labels and any(m.labels.get(k) != v for k, v in labels.items()):
                continue
            total += m.value
        return total

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        """获取计数器值。"""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float | None:
        """获取仪表盘值。"""
        key = self._make_key(name, labels)
        return self._gauges.get(key)

    def get_histogram(self, name: str, labels: dict[str, str] | None = None) -> list[float]:
        """获取直方图值。"""
        key = self._make_key(name, labels)
        return self._histograms.get(key, [])

    def get_metrics(self) -> list[Metric]:
        """获取所有指标。"""
        return self._metrics.copy()

    def _make_key(self, name: str, labels: dict[str, str] | None = None) -> str:
        """生成指标键。"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# 全局指标实例
metrics = MetricsCollector()


# 预定义指标
class GweiMetrics:
    """Gwei 预定义指标。"""

    @staticmethod
    def record_issue_processed(status: str):
        """记录处理的 Issue。"""
        metrics.increment("gwei_issues_processed_total", {"status": status})

    @staticmethod
    def record_pr_created():
        """记录创建的 PR。"""
        metrics.increment("gwei_prs_created_total")

    @staticmethod
    def record_llm_call(duration: float, model: str):
        """记录 LLM 调用。"""
        metrics.observe("gwei_llm_call_duration_seconds", duration, {"model": model})
        metrics.increment("gwei_llm_calls_total", {"model": model})

    @staticmethod
    def record_vote(pr_id: str, vote: str):
        """记录投票。"""
        metrics.increment("gwei_votes_total", {"pr_id": pr_id, "vote": vote})

    @staticmethod
    def set_active_sessions(count: int):
        """设置活跃会话数。"""
        metrics.set_gauge("gwei_active_sessions", count)

    @staticmethod
    def record_error(error_type: str):
        """记录错误。"""
        metrics.increment("gwei_errors_total", {"type": error_type})
