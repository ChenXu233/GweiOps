# src/agent/state.py
from enum import Enum
from typing import Annotated, Any, TypedDict
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


class AgentState:
    """Agent state class for LangGraph with attribute access support."""

    # Type hints for static analysis
    issue_title: str
    issue_body: str
    repo_url: str
    repo_name: str
    issue_number: int
    status: str
    issue_type: str | None
    analysis: str
    reproduction_result: str | None
    error_stack: str | None
    patches: Annotated[list[PatchProposal], operator.add]
    selected_patch: str | None
    pr_url: str | None
    pr_number: int | None
    error_count: int
    messages: Annotated[list[str], operator.add]

    def __init__(self, **kwargs: Any):
        # Set defaults
        self.__dict__.update({
            "issue_title": "",
            "issue_body": "",
            "repo_url": "",
            "repo_name": "",
            "issue_number": 0,
            "status": SessionStatus.INIT,
            "issue_type": None,
            "analysis": "",
            "reproduction_result": None,
            "error_stack": None,
            "patches": [],
            "selected_patch": None,
            "pr_url": None,
            "pr_number": None,
            "error_count": 0,
            "messages": [],
        })
        # Override with provided values
        self.__dict__.update(kwargs)

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.__dict__[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.__dict__.get(key, default)

    @property
    def should_fail(self) -> bool:
        return self.error_count >= 3

    @property
    def needs_reproduction(self) -> bool:
        return self.issue_type == IssueType.BUG.value

    @property
    def needs_code_change(self) -> bool:
        t = self.issue_type
        return t in (IssueType.BUG.value, IssueType.FEATURE.value)
