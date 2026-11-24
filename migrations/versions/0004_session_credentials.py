"""Add owner credentials without inheriting authority from legacy IDs."""
import sqlalchemy as sa
from alembic import op

revision = '0004_session_credentials'
down_revision = '0003_request_leases'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'session_owner_credentials',
        sa.Column('session_id', sa.String(32), sa.ForeignKey('sessions.session_id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('digest', sa.LargeBinary(32), nullable=False),
        sa.Column('mode', sa.String(6), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('octet_length(digest) = 32', name='owner_digest_length'),
        sa.CheckConstraint("mode IN ('cookie', 'bearer')", name='owner_mode'),
        sa.CheckConstraint("expires_at = issued_at + interval '24 hours'", name='owner_expiry'),
    )


def downgrade():
    raise RuntimeError('Credential downgrade is disabled; close session ingress and restore a verified backup.')
