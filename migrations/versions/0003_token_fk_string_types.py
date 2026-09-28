"""Align session/API-key foreign keys with string access-token IDs."""

from alembic import op

revision = "0003_token_fk_string_types"
down_revision = "0002_aggregate_bucket_start"
branch_labels = None
depends_on = None


def _upgrade_column(table: str, column: str, constraint: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite accepts the existing values in the legacy INTEGER declaration,
        # while fresh databases already use VARCHAR from the corrected model.
        return
    op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"')
    op.execute(
        f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE VARCHAR(40) '
        f'USING "{column}"::varchar'
    )
    op.execute(
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" '
        f'FOREIGN KEY ("{column}") REFERENCES "access_tokens"("id") ON DELETE CASCADE'
    )


def upgrade() -> None:
    _upgrade_column("account_sessions", "token_id", "account_sessions_token_id_fkey")
    _upgrade_column("api_keys", "parent_token_id", "api_keys_parent_token_id_fkey")


def downgrade() -> None:
    # Converting string IDs back to integers is unsafe because production token
    # IDs are opaque strings. Keep the safer string schema on downgrade.
    pass
