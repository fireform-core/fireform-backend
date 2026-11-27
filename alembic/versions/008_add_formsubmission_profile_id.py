"""add profile_id to formsubmission

Revision ID: 008
Revises: 007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("formsubmission", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_formsubmission_profile_id"), ["profile_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_formsubmission_profile_id_profiles",
            "profiles",
            ["profile_id"],
            ["profile_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("formsubmission", schema=None) as batch_op:
        batch_op.drop_constraint("fk_formsubmission_profile_id_profiles", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_formsubmission_profile_id"))
        batch_op.drop_column("profile_id")
