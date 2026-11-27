"""Store each conflict's category on the row, computed once when it's recorded.

Previously computed on every GraphQL read (synchronously, including a live LLM call for
whatever a rule couldn't classify) via causes.cause_of(), via an unbounded in-process dict
cache that didn't survive a restart or stay consistent across replicas. Now computed once
in ConflictService.record_failure and read straight off the row. Nullable: existing rows
get NULL and the read path falls back to the rule-only classifier for those (see
_conflict_to_gql), never an LLM call for history that predates this column.

Revision ID: 0022_conflict_category_columns
Revises: 0021_conflict_severity_rules
Create Date: 2026-11-27
"""

from __future__ import annotations

from alembic import op

revision = "0022_conflict_category_columns"
down_revision = "0021_conflict_severity_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE order_conflicts ADD COLUMN category TEXT;
        ALTER TABLE order_conflicts ADD COLUMN category_source TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE order_conflicts DROP COLUMN IF EXISTS category;
        ALTER TABLE order_conflicts DROP COLUMN IF EXISTS category_source;
        """
    )
