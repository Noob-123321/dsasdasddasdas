"""Add the detection tables: chatter snapshots, account cache, channel intel.

The live ``data/tvb.db`` keeps its migrated ``samples`` schema untouched; the
detection layer stores everything volatile on these three new tables.
"""
from alembic import op

from app import models  # noqa: F401

revision = "0005_detection"
down_revision = "0004_score_warning_codes"
branch_labels = None
depends_on = None

_TABLES = ("chatter_snapshots", "chatter_accounts", "channel_intel")


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        models.Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLES):
        models.Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
