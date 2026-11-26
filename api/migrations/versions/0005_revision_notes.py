"""revision_notes: cited revision notes per user + document + concept (SPEC 9.5)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'revision_notes',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('concept', sa.Text(), nullable=False),
        sa.Column('sentences', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('dropped', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ix_revision_notes_user_doc_concept', 'revision_notes', ['user_id', 'document_id', 'concept', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_revision_notes_user_doc_concept', table_name='revision_notes')
    op.drop_table('revision_notes')
