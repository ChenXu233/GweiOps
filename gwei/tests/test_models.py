# tests/test_models.py
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from src.db.base import Base
from src.models.project import Project
from src.models.issue import Issue
from src.models.session import AgentSession
from src.models.patch import Patch
from src.models.pr import PullRequest
from src.models.vote import ApprovalVote

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_project(db_session: AsyncSession):
    project = Project(
        github_id=12345,
        name="test-repo",
        config={"mode": "saas"},
    )
    db_session.add(project)
    await db_session.flush()

    assert project.id is not None
    assert project.github_id == 12345
    assert project.name == "test-repo"
    assert project.config == {"mode": "saas"}


@pytest.mark.asyncio
async def test_create_issue(db_session: AsyncSession):
    project = Project(github_id=12345, name="test-repo")
    db_session.add(project)
    await db_session.flush()

    issue = Issue(
        github_id=100,
        project_id=project.id,
        number=1,
        title="Test issue",
        body="This is a test issue",
        status="OPEN",
    )
    db_session.add(issue)
    await db_session.flush()

    assert issue.id is not None
    assert issue.github_id == 100
    assert issue.status == "OPEN"


@pytest.mark.asyncio
async def test_agent_session_lifecycle(db_session: AsyncSession):
    project = Project(github_id=12345, name="test-repo")
    db_session.add(project)
    await db_session.flush()

    issue = Issue(github_id=100, project_id=project.id, number=1, title="Bug")
    db_session.add(issue)
    await db_session.flush()

    session = AgentSession(
        issue_id=issue.id,
        status="INIT",
        state={"foo": "bar"},
    )
    db_session.add(session)
    await db_session.flush()

    assert session.status == "INIT"
    assert session.state == {"foo": "bar"}

    session.status = "ANALYZING"
    await db_session.flush()
    assert session.status == "ANALYZING"


@pytest.mark.asyncio
async def test_full_issue_to_pr_flow(db_session: AsyncSession):
    project = Project(github_id=12345, name="test-repo")
    db_session.add(project)
    await db_session.flush()

    issue = Issue(github_id=100, project_id=project.id, number=1, title="Bug")
    db_session.add(issue)
    await db_session.flush()

    sess = AgentSession(issue_id=issue.id, status="INIT")
    db_session.add(sess)
    await db_session.flush()

    patch = Patch(
        session_id=sess.id,
        type="HOTFIX",
        diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-foo\n+bar",
        risk_assessment="Low risk",
    )
    db_session.add(patch)
    await db_session.flush()

    pr = PullRequest(
        patch_id=patch.id,
        github_id=200,
        number=1,
        url="https://github.com/test-repo/pull/1",
        status="OPEN",
    )
    db_session.add(pr)
    await db_session.flush()

    vote = ApprovalVote(
        pr_id=pr.id,
        voter_id=42,
        voter_role="collaborator",
        vote="approve",
    )
    db_session.add(vote)
    await db_session.flush()

    assert patch.type == "HOTFIX"
    assert pr.url == "https://github.com/test-repo/pull/1"
    assert vote.vote == "approve"
