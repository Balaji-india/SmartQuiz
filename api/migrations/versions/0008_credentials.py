"""Credentials: roles, wallets, attempt hashes, result batches, badges, co-signatures, document revocation (SPEC 9.9)

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(16), server_default='learner', nullable=False))
    op.add_column('users', sa.Column('wallet_address', sa.String(42), nullable=True))

    op.create_table(
        'result_batches',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('batch_id', sa.String(66), nullable=False, unique=True),
        sa.Column('root', sa.String(66), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('anchor_tx', sa.String(66), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column('attempts', sa.Column('attempt_hash', sa.String(66), nullable=True))
    op.add_column('attempts', sa.Column('attempt_salt', sa.String(64), nullable=True))
    op.add_column('attempts', sa.Column('batch_id', sa.UUID(), sa.ForeignKey('result_batches.id'), nullable=True))
    op.create_index('ix_attempts_batch_id', 'attempts', ['batch_id'])

    op.create_table(
        'badges',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('concept', sa.Text(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=True, unique=True),
        sa.Column('holder_address', sa.String(42), nullable=False),
        sa.Column('custodial', sa.Boolean(), nullable=False),
        sa.Column('concept_hash', sa.String(66), nullable=False),
        sa.Column('evidence_hash', sa.String(66), nullable=False),
        sa.Column('evidence_attempt_ids', sa.ARRAY(sa.UUID()), server_default='{}', nullable=False),
        sa.Column('mint_tx', sa.String(66), nullable=True),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('revoke_tx', sa.String(66), nullable=True),
        sa.Column('revoke_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_badges_user_document', 'badges', ['user_id', 'document_id'])

    op.create_table(
        'cosignatures',
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), primary_key=True),
        sa.Column('educator_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('educator_address', sa.String(42), nullable=False),
        sa.Column('signature', sa.String(132), nullable=False),
        sa.Column('cosign_tx', sa.String(66), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column('documents', sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('documents', sa.Column('revoke_tx', sa.String(66), nullable=True))
    op.add_column('documents', sa.Column('revoke_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'revoke_reason')
    op.drop_column('documents', 'revoke_tx')
    op.drop_column('documents', 'revoked')
    op.drop_table('cosignatures')
    op.drop_index('ix_badges_user_document', table_name='badges')
    op.drop_table('badges')
    op.drop_index('ix_attempts_batch_id', table_name='attempts')
    op.drop_column('attempts', 'batch_id')
    op.drop_column('attempts', 'attempt_salt')
    op.drop_column('attempts', 'attempt_hash')
    op.drop_table('result_batches')
    op.drop_column('users', 'wallet_address')
    op.drop_column('users', 'role')
