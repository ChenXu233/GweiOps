# src/agent/state.py
from enum import Enum
from typing import Annotated, TypedDict
import operator


class SessionStatus(str, Enum):
    INIT = "INIT"
    ANALYZING = "ANALYZING"
    REPRODUCING = "REPRODUCING"
    LOCATING = "LOCATING"
    GENERATING = "GENERATING"
    WAITING = "WAITING"
    CREATING_PR = "CREATING_PR"
    DONE = "DONE"
    FAILED = "FAILED"


class IssueType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    DOCS = "docs"
    DUPLICATE = "duplicate"
    QUESTION = "question"
    UNKNOWN = "unknown"


class PatchProposal(TypedDict):
    type: str  # HOTFIX, PROPER, REFACTOR
    diff: str
    risk: str
    description: str


class AgentState(TypedDict, total=False):
    """Agent state for LangGraph (TypedDict with reducer annotations)."""

    issue_title: str
    issue_body: str
    repo_url: str
    repo_name: str
    issue_number: int
    status: SessionStatus
    issue_type: IssueType | None
    analysis: str
    reproduction_result: str | None
    error_stack: str | None
    patches: Annotated[list[PatchProposal], operator.add]
    selected_patch: str | None
    pr_url: str | None
    pr_number: int | None
    error_count: int
    messages: Annotated[list[str], operator.add]


def should_fail(state: AgentState) -> bool:
    return state.get("error_count", 0) >= 3


def needs_reproduction(state: AgentState) -> bool:
    return state.get("issue_type") == IssueType.BUG


def needs_code_change(state: AgentState) -> bool:
    t = state.get("issue_type")
    return t in (IssueType.BUG, IssueType.FEATURE)
