"""
Model mới: Quản lý DAG Module trong pipeline SDLC
Bao gồm: Module, ModuleDependency, ModuleAttempt
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base


class Module(Base):
    """
    Bảng lưu từng module trong đồ thị phụ thuộc (DAG).
    Thay thế việc lưu in-memory trong orchestrator.
    """
    __tablename__ = "modules"

    id_module     = Column(Integer, primary_key=True, autoincrement=True)
    id_design     = Column(Integer, ForeignKey("design_specs.id_design"))
    module_key    = Column(String(100))   # Khóa định danh nội bộ, e.g. "auth_module"
    module_name   = Column(String(200))   # Tên hiển thị
    description   = Column(Text)         # Mô tả chức năng module
    module_type   = Column(String(50))   # BACKEND / FRONTEND / DATABASE / CONFIG
    module_order  = Column(Integer)      # Thứ tự sau Topological Sort (0 = chạy đầu tiên)
    specification = Column(Text)         # JSON spec đầy đủ từ Design Agent
    status        = Column(
        String(20), default="PENDING"
    )  # PENDING / CODING / TESTING / PASSED / FAILED / SKIPPED
    retry_count   = Column(Integer, default=0)
    max_retries   = Column(Integer, default=3)
    is_testable   = Column(Boolean, default=True)   # False nếu là file config, không test được
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModuleDependency(Base):
    """
    Bảng lưu các cạnh (edges) của đồ thị phụ thuộc DAG.
    module A phụ thuộc module B → B phải hoàn thành trước A.
    """
    __tablename__ = "module_dependencies"

    id_module            = Column(Integer, ForeignKey("modules.id_module"), primary_key=True)
    depends_on_module_id = Column(Integer, ForeignKey("modules.id_module"), primary_key=True)
    id_design            = Column(Integer, ForeignKey("design_specs.id_design"))


class ModuleAttempt(Base):
    """
    Bảng lưu lịch sử mỗi lần Dev Agent thử sinh code / sửa lỗi cho một module.
    Giúp theo dõi quá trình self-correction và persist state qua các request.
    """
    __tablename__ = "module_attempts"

    id_attempt      = Column(Integer, primary_key=True, autoincrement=True)
    id_module       = Column(Integer, ForeignKey("modules.id_module"))
    attempt_number  = Column(Integer)              # Lần thử thứ mấy (1, 2, 3...)
    attempt_type    = Column(String(20))           # CODING (lần đầu) / FIXING (sửa lỗi)
    status          = Column(String(20))           # RUNNING / SUCCESS / FAILED
    error_summary   = Column(Text, nullable=True)  # Tóm tắt lỗi từ Docker log
    source_revision = Column(Text, nullable=True)  # JSON snapshot code của lần thử này
    started_at      = Column(DateTime, default=datetime.utcnow)
    finished_at     = Column(DateTime, nullable=True)
