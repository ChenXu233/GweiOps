# src/agent/graph.py
from langgraph.graph import StateGraph, END
from src.agent.state import AgentState, SessionStatus, IssueType
from src.agent.nodes import (
    analyze_issue,
    generate_patches,
    wait_for_user_selection,
    create_pr,
)


def route_after_analysis(state: AgentState) -> str:
    """分析后路由：Bug 需要复现，其他类型直接生成方案。"""
    issue_type = state.get("issue_type")
    if issue_type == IssueType.BUG:
        return "reproducing"
    return "generating"


def route_after_patches(state: AgentState) -> str:
    """生成 Patch 后：如果已选择方案则创建 PR，否则等待用户。"""
    if state.get("selected_patch"):
        return "creating_pr"
    return "waiting"


def create_gwei_graph() -> StateGraph:
    """构建 Gwei Agent 状态图。"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("analyze", analyze_issue)
    workflow.add_node("generate_patches", generate_patches)
    workflow.add_node("wait_for_user", wait_for_user_selection)
    workflow.add_node("create_pr", create_pr)

    # 设置入口
    workflow.set_entry_point("analyze")

    # 添加边
    workflow.add_conditional_edges(
        "analyze",
        route_after_analysis,
        {
            "reproducing": "generate_patches",
            "generating": "generate_patches",
        },
    )
    workflow.add_conditional_edges(
        "generate_patches",
        route_after_patches,
        {
            "waiting": "wait_for_user",
            "creating_pr": "create_pr",
        },
    )
    workflow.add_edge("wait_for_user", END)
    workflow.add_edge("create_pr", END)

    return workflow


# 全局 graph 实例
gwei_graph = create_gwei_graph().compile()
