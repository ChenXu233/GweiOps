# engine/harness/__init__.py
"""外部 harness 适配:在工作区里跑一条命令,收回一份报告。"""

from .adapter import REPORT_NAME, HarnessResult, build_task, run_harness

__all__ = ["HarnessResult", "run_harness", "build_task", "REPORT_NAME"]
