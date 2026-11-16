"""控制台会话与对话表进迁移链

这两张表一直由应用启动时的 `ensure_schema`(checkfirst)建,不在迁移里。容器部署
跑的是 `alembic upgrade head`,于是"库里的表"与"迁移说有的表"从此分叉:
任何依赖表存在的迁移(比如给它们加策略)在干净库上都会挂在 `relation does not exist`。

这一版把表补进链里,形状与 `engine/db/models/console_session.py` 一致。
老库上表已存在,`checkfirst` 语义(-- 见下)让这一版变成空操作。

Revision ID: 012
Revises: 011
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _tables() -> list[sa.Table]:
    from engine.db.models.console_session import ConsoleMessageRow, ConsoleSessionRow

    return [ConsoleSessionRow.__table__, ConsoleMessageRow.__table__]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind, checkfirst=True)
