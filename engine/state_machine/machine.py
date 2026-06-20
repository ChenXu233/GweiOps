# engine/state_machine/machine.py
from typing import Dict, Any, Optional, Callable, Awaitable
from .states import WorkflowState
from .transitions import TransitionRule, DEFAULT_TRANSITIONS


class StateMachine:
    """状态机核心"""

    def __init__(self, initial_state: WorkflowState = WorkflowState.S0_PERCEIVED):
        self.current_state = initial_state
        self.transitions: Dict[str, TransitionRule] = {}
        self.on_transition_callbacks: list[Callable] = []

        # 加载默认转换规则
        for rule in DEFAULT_TRANSITIONS:
            key = f"{rule.from_state.value}:{rule.condition}"
            self.transitions[key] = rule

    def add_transition(self, rule: TransitionRule):
        """添加转换规则"""
        key = f"{rule.from_state.value}:{rule.condition}"
        self.transitions[key] = rule

    def on_transition(self, callback: Callable):
        """注册转换回调"""
        self.on_transition_callbacks.append(callback)

    async def trigger(self, condition: str, context: Dict[str, Any] = None) -> bool:
        """触发状态转换"""
        key = f"{self.current_state.value}:{condition}"
        rule = self.transitions.get(key)

        if not rule:
            return False

        # 执行转换
        old_state = self.current_state
        self.current_state = rule.to_state

        # 调用回调
        for callback in self.on_transition_callbacks:
            await callback(old_state, rule.to_state, context or {})

        return True

    def get_available_transitions(self) -> list[str]:
        """获取当前状态可用的转换"""
        return [
            rule.condition
            for key, rule in self.transitions.items()
            if key.startswith(f"{self.current_state.value}:")
        ]

    def is_terminal(self) -> bool:
        """是否为终止状态"""
        return self.current_state in (WorkflowState.DONE, WorkflowState.FAILED)

    def reset(self):
        """重置状态机"""
        self.current_state = WorkflowState.S0_PERCEIVED
