"""questions.distractors and quizzes.hash_version (SPEC 9.2)

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows keep Review 1 behaviour: no distractors, hash v1.
    op.add_column(
        'questions',
        sa.Column('distractors', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column('quizzes', sa.Column('hash_version', sa.Integer(), server_default=sa.text('1'), nullable=False))


def downgrade() -> None:
    op.drop_column('quizzes', 'hash_version')
    op.drop_column('questions', 'distractors')
