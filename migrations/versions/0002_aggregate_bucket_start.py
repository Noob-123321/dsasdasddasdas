"""Allow one aggregate row per channel, bucket and bucket start."""

from alembic import op

revision = "0002_aggregate_bucket_start"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sample_aggregates") as batch:
        batch.drop_constraint("uq_sample_aggregate", type_="unique")
        batch.create_unique_constraint("uq_sample_aggregate", ["channel_login", "bucket", "bucket_start"])


def downgrade() -> None:
    with op.batch_alter_table("sample_aggregates") as batch:
        batch.drop_constraint("uq_sample_aggregate", type_="unique")
        batch.create_unique_constraint("uq_sample_aggregate", ["channel_login", "bucket"])
