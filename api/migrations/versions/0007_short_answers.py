"""Short-answer questions and checker grading with educator deferral (SPEC 9.7)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('questions', sa.Column('qtype', sa.String(8), server_default='mcq', nullable=False))
    op.add_column('questions', sa.Column('model_answer', sa.Text(), nullable=True))
    op.alter_column('questions', 'dependence_score', existing_type=sa.Float(), nullable=True)
    op.add_column('attempts', sa.Column('grading_status', sa.String(16), server_default='final', nullable=False))
    op.create_table(
        'answer_grades',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('attempt_id', sa.UUID(), sa.ForeignKey('attempts.id'), nullable=False),
        sa.Column('question_id', sa.UUID(), sa.ForeignKey('questions.id'), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.Column('verdict', sa.String(16), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('fact_idxs', sa.ARRAY(sa.Integer()), server_default='{}', nullable=False),
        sa.Column('deferred', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('educator_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('educator_verdict', sa.String(16), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('attempt_id', 'question_id', name='uq_answer_grades_attempt_question'),
    )
    op.create_index('ix_answer_grades_pending', 'answer_grades', ['deferred', 'educator_verdict'])


def downgrade() -> None:
    op.drop_index('ix_answer_grades_pending', table_name='answer_grades')
    op.drop_table('answer_grades')
    op.drop_column('attempts', 'grading_status')
    op.execute("UPDATE questions SET dependence_score = 0 WHERE dependence_score IS NULL")
    op.alter_column('questions', 'dependence_score', existing_type=sa.Float(), nullable=False)
    op.drop_column('questions', 'model_answer')
    op.drop_column('questions', 'qtype')
