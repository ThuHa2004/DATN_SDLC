from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class TestCase(Base):
    __tablename__ = "testcases"
    id_testcase = Column(Integer, primary_key=True, autoincrement=True)
    id_version = Column(Integer, ForeignKey("code_versions.id_version"))
    id_module = Column(Integer, ForeignKey("modules.id_module"), nullable=True)  # Test case thuộc module nào
    test_type = Column(String(20), default="UNIT")        # UNIT / INTEGRATION / E2E
    requirement_id = Column(String(100), nullable=True)   # ID yêu cầu tương ứng trong SRS
    test_name = Column(String(200))
    test_steps = Column(Text)
    expected_result = Column(Text)

class TestRun(Base):
    __tablename__ = "test_runs"
    id_run = Column(Integer, primary_key=True, autoincrement=True)
    id_testcase = Column(Integer, ForeignKey("testcases.id_testcase"))
    id_execution = Column(Integer, ForeignKey("test_executions.id_execution"), nullable=True)
    run_status = Column(String(20))    # PASS / FAIL / SKIP
    error_logs = Column(Text)
    run_at = Column(DateTime, default=datetime.utcnow)

class TestExecution(Base):
    """Bảng mới: Lưu kết quả mỗi lần chạy batch test (theo module hoặc toàn hệ thống)"""
    __tablename__ = "test_executions"
    id_execution = Column(Integer, primary_key=True, autoincrement=True)
    id_module = Column(Integer, ForeignKey("modules.id_module"), nullable=True)   # Test cho module cụ thể
    id_attempt = Column(Integer, ForeignKey("module_attempts.id_attempt"), nullable=True)  # Lần thử thứ mấy
    id_version = Column(Integer, ForeignKey("code_versions.id_version"), nullable=True)
    test_type = Column(String(20), default="UNIT")  # UNIT / INTEGRATION / E2E
    status = Column(String(20), default="RUNNING")  # RUNNING / PASSED / FAILED / ERROR
    total_tests = Column(Integer, default=0)
    passed_tests = Column(Integer, default=0)
    failed_tests = Column(Integer, default=0)
    skipped_tests = Column(Integer, default=0)
    error_logs = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
