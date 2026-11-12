"""add_modules_dag_and_new_columns

Revision ID: 910ee4d382a9
Revises: 7f38cdc35533
Create Date: 2026-11-09 22:40:50.451929

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '910ee4d382a9'
down_revision: Union[str, Sequence[str], None] = '7f38cdc35533'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Tạo bảng mới: modules (phải tạo trước vì các bảng khác FK tới đây) ---
    op.create_table('modules',
        sa.Column('id_module', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_design', sa.Integer(), nullable=True),
        sa.Column('module_key', sa.String(length=100), nullable=True),
        sa.Column('module_name', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('module_type', sa.String(length=50), nullable=True),
        sa.Column('module_order', sa.Integer(), nullable=True),
        sa.Column('specification', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('is_testable', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_design'], ['design_specs.id_design'], name='fk_modules_design'),
        sa.PrimaryKeyConstraint('id_module')
    )

    # --- Tạo bảng mới: module_attempts ---
    op.create_table('module_attempts',
        sa.Column('id_attempt', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_module', sa.Integer(), nullable=True),
        sa.Column('attempt_number', sa.Integer(), nullable=True),
        sa.Column('attempt_type', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('source_revision', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_module'], ['modules.id_module'], name='fk_module_attempts_module'),
        sa.PrimaryKeyConstraint('id_attempt')
    )

    # --- Tạo bảng mới: module_dependencies ---
    op.create_table('module_dependencies',
        sa.Column('id_module', sa.Integer(), nullable=False),
        sa.Column('depends_on_module_id', sa.Integer(), nullable=False),
        sa.Column('id_design', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['depends_on_module_id'], ['modules.id_module'], name='fk_moddep_depends_on'),
        sa.ForeignKeyConstraint(['id_design'], ['design_specs.id_design'], name='fk_moddep_design'),
        sa.ForeignKeyConstraint(['id_module'], ['modules.id_module'], name='fk_moddep_module'),
        sa.PrimaryKeyConstraint('id_module', 'depends_on_module_id')
    )

    # --- Tạo bảng mới: test_executions ---
    op.create_table('test_executions',
        sa.Column('id_execution', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_module', sa.Integer(), nullable=True),
        sa.Column('id_attempt', sa.Integer(), nullable=True),
        sa.Column('id_version', sa.Integer(), nullable=True),
        sa.Column('test_type', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('total_tests', sa.Integer(), nullable=True),
        sa.Column('passed_tests', sa.Integer(), nullable=True),
        sa.Column('failed_tests', sa.Integer(), nullable=True),
        sa.Column('skipped_tests', sa.Integer(), nullable=True),
        sa.Column('error_logs', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_attempt'], ['module_attempts.id_attempt'], name='fk_testexec_attempt'),
        sa.ForeignKeyConstraint(['id_module'], ['modules.id_module'], name='fk_testexec_module'),
        sa.ForeignKeyConstraint(['id_version'], ['code_versions.id_version'], name='fk_testexec_version'),
        sa.PrimaryKeyConstraint('id_execution')
    )

    # --- Thêm cột mới vào các bảng hiện có ---
    op.add_column('agent_logs', sa.Column('correlation_id', sa.String(length=36), nullable=True))

    op.add_column('brd_records', sa.Column('created_at', sa.DateTime(), nullable=True))

    op.alter_column('code_versions', 'version_number',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=50),
               existing_nullable=True)

    op.add_column('design_specs', sa.Column('architecture_json', sa.Text(), nullable=True))
    op.add_column('design_specs', sa.Column('module_plan', sa.Text(), nullable=True))
    op.add_column('design_specs', sa.Column('created_at', sa.DateTime(), nullable=True))

    op.add_column('projects', sa.Column('updated_at', sa.DateTime(), nullable=True))

    op.add_column('sandbox_environments', sa.Column('created_at', sa.DateTime(), nullable=True))

    op.add_column('source_files', sa.Column('id_module', sa.Integer(), nullable=True))
    op.add_column('source_files', sa.Column('checksum', sa.String(length=64), nullable=True))
    op.alter_column('source_files', 'file_name',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.String(length=500),
               existing_nullable=True)
    op.alter_column('source_files', 'file_path',
               existing_type=sa.VARCHAR(length=500),
               type_=sa.String(length=1000),
               existing_nullable=True)
    op.create_foreign_key('fk_sourcefiles_module', 'source_files', 'modules', ['id_module'], ['id_module'])

    op.add_column('srs_records', sa.Column('created_at', sa.DateTime(), nullable=True))

    op.add_column('test_runs', sa.Column('id_execution', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_testruns_execution', 'test_runs', 'test_executions', ['id_execution'], ['id_execution'])

    op.add_column('testcases', sa.Column('id_module', sa.Integer(), nullable=True))
    op.add_column('testcases', sa.Column('test_type', sa.String(length=20), nullable=True))
    op.add_column('testcases', sa.Column('requirement_id', sa.String(length=100), nullable=True))
    op.create_foreign_key('fk_testcases_module', 'testcases', 'modules', ['id_module'], ['id_module'])

    op.add_column('user_feedbacks', sa.Column('id_project', sa.String(length=36), nullable=True))
    op.add_column('user_feedbacks', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.create_foreign_key('fk_feedbacks_project', 'user_feedbacks', 'projects', ['id_project'], ['id_project'])


def downgrade() -> None:
    """Downgrade schema."""
    # --- Xóa FK và cột từ bảng hiện có ---
    op.drop_constraint('fk_feedbacks_project', 'user_feedbacks', type_='foreignkey')
    op.drop_column('user_feedbacks', 'created_at')
    op.drop_column('user_feedbacks', 'id_project')

    op.drop_constraint('fk_testcases_module', 'testcases', type_='foreignkey')
    op.drop_column('testcases', 'requirement_id')
    op.drop_column('testcases', 'test_type')
    op.drop_column('testcases', 'id_module')

    op.drop_constraint('fk_testruns_execution', 'test_runs', type_='foreignkey')
    op.drop_column('test_runs', 'id_execution')

    op.drop_column('srs_records', 'created_at')

    op.drop_constraint('fk_sourcefiles_module', 'source_files', type_='foreignkey')
    op.alter_column('source_files', 'file_path',
               existing_type=sa.String(length=1000),
               type_=sa.VARCHAR(length=500),
               existing_nullable=True)
    op.alter_column('source_files', 'file_name',
               existing_type=sa.String(length=500),
               type_=sa.VARCHAR(length=100),
               existing_nullable=True)
    op.drop_column('source_files', 'checksum')
    op.drop_column('source_files', 'id_module')

    op.drop_column('sandbox_environments', 'created_at')
    op.drop_column('projects', 'updated_at')

    op.drop_column('design_specs', 'created_at')
    op.drop_column('design_specs', 'module_plan')
    op.drop_column('design_specs', 'architecture_json')

    op.alter_column('code_versions', 'version_number',
               existing_type=sa.String(length=50),
               type_=sa.VARCHAR(length=20),
               existing_nullable=True)

    op.drop_column('brd_records', 'created_at')
    op.drop_column('agent_logs', 'correlation_id')

    # --- Xóa bảng mới (theo thứ tự ngược dependency) ---
    op.drop_table('test_executions')
    op.drop_table('module_dependencies')
    op.drop_table('module_attempts')
    op.drop_table('modules')
