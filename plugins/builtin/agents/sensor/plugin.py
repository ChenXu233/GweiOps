# plugins/builtin/agents/sensor/plugin.py
from typing import Dict, Any, List

from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType
from engine.llm.client import LLMService
from .labeler import LabelGenerator
from .completeness import CompletenessChecker
from .duplicate import DuplicateDetector


class SensorAgent(PluginBase):
    """感知智能体 - 使用 LLM 进行 Issue 分析"""

    def __init__(self, llm_service: LLMService | None = None):
        self.llm = llm_service or LLMService()
        self.labeler = LabelGenerator()
        self.completeness = CompletenessChecker()
        self.duplicate = DuplicateDetector()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="sensor-agent",
            version="2.0.0",
            type=PluginType.AGENT,
            description="感知智能体，使用 LLM 分析 Issue 内容并提供智能回复",
            triggers=[
                {"type": "event", "events": ["issue.created", "issue.edited"]},
            ],
            capabilities=[
                "issue.label",
                "issue.completeness_check",
                "issue.duplicate_detection",
                "issue.llm_analysis",
            ],
        )

    async def on_startup(self):
        """启动时初始化"""
        pass

    async def on_shutdown(self):
        """关闭时释放资源"""
        pass

    async def health_check(self) -> bool:
        """健康检查"""
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件（事件触发）"""
        if event in ("issue.created", "issue.edited"):
            return await self._process_issue(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务（调度智能体触发）"""
        if task == "label":
            labels = self.labeler.generate(params.get("title", ""), params.get("body", ""))
            return {"labels": labels}
        elif task == "check_completeness":
            report = self.completeness.check(params.get("body", ""))
            return {"is_complete": report.is_complete, "missing": report.missing_fields}
        elif task == "analyze":
            return await self._analyze_issue_content(
                params.get("title", ""),
                params.get("body", ""),
            )
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _analyze_issue_content(self, title: str, body: str) -> Dict[str, Any]:
        """
        使用 LLM 分析 Issue 内容，提供智能分析结果

        Args:
            title: Issue 标题
            body: Issue 内容

        Returns:
            包含分析结果的字典
        """
        # 基础分析
        labels = self.labeler.generate(title, body)
        completeness = self.completeness.check(body)

        # LLM 分析
        system_prompt = """你是一个代码分析专家。请分析以下 Issue 内容，提供：
1. 问题摘要（一句话总结）
2. 问题分类（bug/feature/docs/other）
3. 影响范围评估（low/medium/high/critical）
4. 建议的下一步行动
5. 相关的技术栈或模块

请用 JSON 格式回复，包含以下字段：
- summary: 问题摘要
- category: 问题分类
- impact: 影响范围
- next_steps: 建议的下一步行动（数组）
- related_tech: 相关技术栈（数组）"""

        user_prompt = f"""Issue 标题: {title}

Issue 内容:
{body}

请分析这个 Issue。"""

        try:
            llm_result = await self.llm.call(system_prompt, user_prompt)
            analysis = llm_result.content
        except Exception as e:
            analysis = f"LLM 分析失败: {str(e)}"

        return {
            "status": "ok",
            "labels": labels,
            "is_complete": completeness.is_complete,
            "missing_fields": completeness.missing_fields,
            "completeness_score": completeness.score,
            "llm_analysis": analysis,
        }

    def _format_reply(self, analysis: Dict[str, Any]) -> str:
        """
        格式化回复内容，用于 Issue 评论

        Args:
            analysis: 分析结果

        Returns:
            格式化后的 Markdown 文本
        """
        lines = ["## Issue 分析报告\n"]

        # 标签
        if analysis.get("labels"):
            labels_str = ", ".join([f"`{label}`" for label in analysis["labels"]])
            lines.append(f"### 标签\n{labels_str}\n")

        # 完整性检查
        if not analysis.get("is_complete", True):
            missing = ", ".join(analysis.get("missing_fields", []))
            lines.append(f"### 完整性检查\n")
            lines.append(f"- 缺少字段: {missing}")
            lines.append(f"- 完整性分数: {analysis.get('completeness_score', 0):.0%}\n")

        # LLM 分析
        if analysis.get("llm_analysis"):
            lines.append("### LLM 分析结果\n")
            lines.append(analysis["llm_analysis"])
            lines.append("")

        return "\n".join(lines)

    async def _process_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Issue 事件"""
        issue = data.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")

        # 使用 LLM 分析
        analysis = await self._analyze_issue_content(title, body)

        # 格式化回复
        reply = self._format_reply(analysis)

        return {
            **analysis,
            "reply": reply,
        }
