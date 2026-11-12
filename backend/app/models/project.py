from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base

class Project(Base):
    __tablename__ = "projects"

    id_project = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    id_user = Column(Integer, ForeignKey("users.id_user"))
    project_name = Column(String(150), nullable=False)
    project_status = Column(String(50), default="INIT")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Quan hệ để dễ dàng truy vấn thông tin người tạo dự án
    owner = relationship("User")
