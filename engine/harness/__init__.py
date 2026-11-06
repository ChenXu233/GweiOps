# engine/harness/__init__.py
"""外部 harness 适配:在工作区里跑一条命令,收回一份报告。"""

from engine.shared.config import config

from .adapter import REPORT_NAME, HarnessResult, build_env, build_task, run_harness

# 凭据不由部署方进容器手配:写进这个 scope,平台起容器时注入成大写环境变量。
config.register_scope(name="harness-env", prefix="HARNESS_ENV_")

__all__ = ["HarnessResult", "run_harness", "build_task", "build_env", "REPORT_NAME"]
