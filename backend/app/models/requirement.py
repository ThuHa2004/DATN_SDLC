from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class BRDRecord(Base):
    __tablename__ = "brd_records"
    id_brd = Column(Integer, primary_key=True, autoincrement=True)
    id_project = Column(String(36), ForeignKey("projects.id_project"))
    business_goals = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class SRSRecord(Base):
    __tablename__ = "srs_records"
    id_srs = Column(Integer, primary_key=True, autoincrement=True)
    id_brd = Column(Integer, ForeignKey("brd_records.id_brd"))
    functional_specs = Column(Text)   # Lưu định dạng JSON
    created_at = Column(DateTime, default=datetime.utcnow)

class DesignSpec(Base):
    __tablename__ = "design_specs"
    id_design = Column(Integer, primary_key=True, autoincrement=True)
    id_srs = Column(Integer, ForeignKey("srs_records.id_srs"))
    db_schema = Column(Text)           # Lược đồ CSDL định dạng JSON
    ui_ux_template = Column(Text)      # Cấu hình UI/UX
    architecture_json = Column(Text)   # JSON chứa toàn bộ DAG modules từ Design Agent
    module_plan = Column(Text)         # JSON thứ tự thực thi module (topological order)
    created_at = Column(DateTime, default=datetime.utcnow)
