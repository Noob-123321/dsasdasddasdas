"""Store language-neutral score warning codes next to the Russian text.

Snapshots written before this revision have ``warning_codes`` NULL, which is
how the API tells a caller that ``explanation`` is prose and cannot be
translated; every newer snapshot carries a list (possibly empty).
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_score_warning_codes"
down_revision = "0003_token_fk_string_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("score_snapshots", sa.Column("warning_codes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("score_snapshots") as batch:
        batch.drop_column("warning_codes")
