"""mastery table: BKT per user + document + concept (SPEC 9.4)

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Starts empty; scripts/backfill_mastery.py replays existing attempts.
    op.create_table(
        'mastery',
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), primary_key=True),
        sa.Column('concept', sa.Text(), primary_key=True),
        sa.Column('p_mastery', sa.Float(), nullable=False),
        sa.Column('answered', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('mastery')
