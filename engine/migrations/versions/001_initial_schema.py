"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # projects
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("github_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config", postgresql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )

    # issues
    op.create_table(
        "issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("github_id", sa.Integer(), unique=True, nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", name="fk_issues_project_id_projects"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("labels", postgresql.JSON(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_issues"),
        sa.Index("ix_issues_project_id", "project_id"),
        sa.Index("ix_issues_github_id", "github_id"),
    )

    # agent_sessions
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "issue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("issues.id", name="fk_agent_sessions_issue_id_issues"),
            nullable=False,
        ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("state", postgresql.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agent_sessions"),
        sa.Index("ix_agent_sessions_issue_id", "issue_id"),
    )

    # patches
    op.create_table(
        "patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_sessions.id", name="fk_patches_session_id_agent_sessions"
            ),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("risk_assessment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_patches"),
        sa.Index("ix_patches_session_id", "session_id"),
    )

    # pull_requests
    op.create_table(
        "pull_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "patches.id", name="fk_pull_requests_patch_id_patches"
            ),
            nullable=False,
        ),
        sa.Column("github_id", sa.Integer(), unique=True, nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pull_requests"),
        sa.Index("ix_pull_requests_patch_id", "patch_id"),
    )

    # approval_votes
    op.create_table(
        "approval_votes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "pull_requests.id", name="fk_approval_votes_pr_id_pull_requests"
            ),
            nullable=False,
        ),
        sa.Column("voter_id", sa.Integer(), nullable=False),
        sa.Column("voter_role", sa.String(50), nullable=False),
        sa.Column("vote", sa.String(50), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approval_votes"),
        sa.Index("ix_approval_votes_pr_id", "pr_id"),
    )


def downgrade() -> None:
    op.drop_table("approval_votes")
    op.drop_table("pull_requests")
    op.drop_table("patches")
    op.drop_table("agent_sessions")
    op.drop_table("issues")
    op.drop_table("projects")
    op.execute("DROP EXTENSION IF EXISTS vector")