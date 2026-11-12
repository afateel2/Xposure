"""auth: app_user and user_session tables (real reviewer identity)

Revision ID: 8c3f21a9d1e5
Revises: 5b7d1e9a3c40
Create Date: 2026-10-15 00:00:00.000000

Hand written for the same reason 5b7d1e9a3c40 is: autogenerate also
proposes touching the LangGraph checkpoint tables, which must not happen.
See app/auth.py and app/db/models.py (AppUser/UserSession) for what these
hold and why.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8c3f21a9d1e5'
down_revision: Union[str, None] = '5b7d1e9a3c40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('name_en', sa.String(), nullable=False),
        sa.Column('name_ar', sa.String(), nullable=False),
        sa.Column('job_title_en', sa.String(), nullable=True),
        sa.Column('job_title_ar', sa.String(), nullable=True),
        sa.Column('role', sa.String(), nullable=False, server_default='reviewer'),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_app_user_email', 'app_user', ['email'], unique=True)

    op.create_table(
        'user_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_session_token_hash', 'user_session', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_session_token_hash', table_name='user_session')
    op.drop_table('user_session')
    op.drop_index('ix_app_user_email', table_name='app_user')
    op.drop_table('app_user')
