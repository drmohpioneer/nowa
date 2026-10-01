"""Durable ordered snapshots of evening questions."""

import sqlalchemy as sa
from alembic import op

revision = '11'
down_revision = '10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evenings", sa.Column("paper_start", sa.Time()))
    op.add_column("evenings", sa.Column("paper_end", sa.Time()))
    op.create_table(
        'report_questions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinic_id', sa.Integer(), sa.ForeignKey('clinics.id'), nullable=False),
        sa.Column('evening_id', sa.Integer(), sa.ForeignKey('evenings.id'), nullable=False),
        sa.Column('question_id', sa.Integer(), sa.ForeignKey('questions.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_reason', sa.Text()),
        sa.UniqueConstraint('evening_id', 'question_id'),
    )
    op.create_index('ix_report_questions_clinic_id', 'report_questions', ['clinic_id'])


def downgrade() -> None:
    op.drop_table('report_questions')
    with op.batch_alter_table('evenings') as batch:
        batch.drop_column('paper_end')
        batch.drop_column('paper_start')
