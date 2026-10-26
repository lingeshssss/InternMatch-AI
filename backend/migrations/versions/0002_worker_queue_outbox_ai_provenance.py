"""Replace Redis with PostgreSQL leases/rate limits; durable task queue, email outbox, embedding cache, access and saved-version tracking."""
from alembic import op
import sqlalchemy as sa

revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('embedding_cache',
    sa.Column('model_key', sa.String(length=255), nullable=False),
    sa.Column('text_hash', sa.String(length=64), nullable=False),
    sa.Column('vector', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('model_key', 'text_hash')
    )
    op.create_table('leases',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('owner', sa.String(length=100), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('rate_limits',
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=50), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('dedupe_key', sa.String(length=255), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_owner', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    op.create_index(op.f('ix_tasks_kind'), 'tasks', ['kind'], unique=False)
    op.create_index(op.f('ix_tasks_run_after'), 'tasks', ['run_after'], unique=False)
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)
    op.create_table('email_outbox',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('notification_ids', sa.JSON(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_outbox_status'), 'email_outbox', ['status'], unique=False)
    op.create_index(op.f('ix_email_outbox_user_id'), 'email_outbox', ['user_id'], unique=False)
    op.add_column('job_postings', sa.Column('access_status', sa.String(length=20), nullable=False, server_default='ok'))
    op.add_column('resumes', sa.Column('extraction_status', sa.String(length=20), nullable=False, server_default='ready'))
    op.add_column('resumes', sa.Column('extraction_error', sa.Text(), nullable=True))
    op.add_column('saved_jobs', sa.Column('saved_content_hash', sa.String(length=64), nullable=True))

def downgrade():
    op.drop_column('saved_jobs', 'saved_content_hash')
    op.drop_column('resumes', 'extraction_error')
    op.drop_column('resumes', 'extraction_status')
    op.drop_column('job_postings', 'access_status')
    op.drop_index(op.f('ix_email_outbox_user_id'), table_name='email_outbox')
    op.drop_index(op.f('ix_email_outbox_status'), table_name='email_outbox')
    op.drop_table('email_outbox')
    op.drop_index(op.f('ix_tasks_status'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_run_after'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_kind'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_table('rate_limits')
    op.drop_table('leases')
    op.drop_table('embedding_cache')
