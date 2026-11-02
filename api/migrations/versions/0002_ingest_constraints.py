"""documents: facts_unfaithful and unique (user_id, file_sha256)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('facts_unfaithful', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.create_unique_constraint('uq_documents_user_id_file_sha256', 'documents', ['user_id', 'file_sha256'])


def downgrade() -> None:
    op.drop_constraint('uq_documents_user_id_file_sha256', 'documents', type_='unique')
    op.drop_column('documents', 'facts_unfaithful')
