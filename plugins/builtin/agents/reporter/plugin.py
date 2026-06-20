from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .report import ReviewReportGenerator
from .voting import VotingService


class ReporterAgent(PluginBase):
    """报告智能体"""

    def __init__(self):
        self.report_generator = ReviewReportGenerator()
        self.voting = VotingService()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="reporter-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="报告智能体，生成审查报告和投票",
            triggers=[
                {"type": "event", "events": ["pr.created", "review.completed"]},
            ],
            capabilities=["report.generate", "vote.manage"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event == "review.completed":
            return await self._generate_report(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "generate_report":
            from .report import ReviewResult, ReviewIssue
            issues = [
                ReviewIssue(severity=i["severity"], message=i["message"], line=i.get("line"))
                for i in params.get("issues", [])
            ]
            result = ReviewResult(
                issues=issues,
                score=params.get("score", 0),
                summary=params.get("summary", ""),
            )
            report = self.report_generator.generate_markdown(result)
            return {"report": report}
        elif task == "add_vote":
            result = self.voting.add_vote(
                pr_id=params.get("pr_id", 0),
                voter_id=params.get("voter_id", 0),
                voter_role=params.get("voter_role", ""),
                vote=params.get("vote", ""),
            )
            return {"success": result.success, "message": result.message}
        elif task == "get_vote_status":
            status = self.voting.get_status(params.get("pr_id", 0))
            return {
                "approvals": status.approvals,
                "rejections": status.rejections,
                "is_approved": status.is_approved,
            }
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _generate_report(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from .report import ReviewResult, ReviewIssue
        issues_data = data.get("issues", [])
        issues = [
            ReviewIssue(severity=i["severity"], message=i["message"], line=i.get("line"))
            for i in issues_data
        ]
        result = ReviewResult(
            issues=issues,
            score=data.get("score", 0),
            summary=data.get("summary", ""),
        )
        report = self.report_generator.generate_markdown(result)
        return {"status": "ok", "report": report}
