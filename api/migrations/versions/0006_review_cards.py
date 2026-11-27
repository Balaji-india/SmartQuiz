"""review_cards (FSRS per user + fact) and quizzes.mode (SPEC 9.6)

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'review_cards',
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('fact_id', sa.Integer(), sa.ForeignKey('facts.id'), primary_key=True),
        sa.Column('card', postgresql.JSONB(), nullable=False),
        sa.Column('due', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_rating', sa.Integer(), nullable=False),
    )
    op.create_index('ix_review_cards_user_due', 'review_cards', ['user_id', 'due'])
    op.add_column('quizzes', sa.Column('mode', sa.String(16), server_default='practice', nullable=False))


def downgrade() -> None:
    op.drop_column('quizzes', 'mode')
    op.drop_index('ix_review_cards_user_due', table_name='review_cards')
    op.drop_table('review_cards')
