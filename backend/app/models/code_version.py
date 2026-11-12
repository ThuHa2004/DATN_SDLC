from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class CodeVersion(Base):
    __tablename__ = "code_versions"
    id_version = Column(Integer, primary_key=True, autoincrement=True)
    id_design = Column(Integer, ForeignKey("design_specs.id_design"))
    version_number = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

class SourceFile(Base):
    __tablename__ = "source_files"
    id_file = Column(Integer, primary_key=True, autoincrement=True)
    id_version = Column(Integer, ForeignKey("code_versions.id_version"))
    id_module = Column(Integer, ForeignKey("modules.id_module"), nullable=True)  # Liên kết module sinh ra file này
    file_name = Column(String(500))   # Tăng từ 100 → 500 để chứa path dài
    file_path = Column(String(1000))  # Full path
    checksum = Column(String(64))     # SHA256 để khóa version đã pass test
