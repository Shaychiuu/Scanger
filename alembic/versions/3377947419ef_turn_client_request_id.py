"""turn client_request_id; name unique constraints after all their columns

Revision ID: 3377947419ef
Revises: a15a2c540c2d
Create Date: 2026-10-24 15:03:33.968530
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3377947419ef'
down_revision: Union[str, None] = 'a15a2c540c2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE turn RENAME CONSTRAINT uq_turn_session_id TO uq_turn_session_id_ordinal')
    op.execute('ALTER TABLE search_run RENAME CONSTRAINT uq_search_run_turn_id TO uq_search_run_turn_id_attempt')
    op.add_column('turn', sa.Column('client_request_id', sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        op.f('uq_turn_session_id_client_request_id'), 'turn', ['session_id', 'client_request_id']
    )


def downgrade() -> None:
    op.drop_constraint(op.f('uq_turn_session_id_client_request_id'), 'turn', type_='unique')
    op.drop_column('turn', 'client_request_id')
    op.execute('ALTER TABLE search_run RENAME CONSTRAINT uq_search_run_turn_id_attempt TO uq_search_run_turn_id')
    op.execute('ALTER TABLE turn RENAME CONSTRAINT uq_turn_session_id_ordinal TO uq_turn_session_id')
