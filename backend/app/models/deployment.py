from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class SandboxEnvironment(Base):
    __tablename__ = "sandbox_environments"
    id_sandbox = Column(Integer, primary_key=True, autoincrement=True)
    id_version = Column(Integer, ForeignKey("code_versions.id_version"))
    preview_port = Column(Integer, unique=True)
    container_status = Column(String(20))  # BUILDING / RUNNING / STOPPED / ERROR
    created_at = Column(DateTime, default=datetime.utcnow)

class UserFeedback(Base):
    __tablename__ = "user_feedbacks"
    id_feedback = Column(Integer, primary_key=True, autoincrement=True)
    id_sandbox = Column(Integer, ForeignKey("sandbox_environments.id_sandbox"), nullable=True)
    id_project = Column(String(36), ForeignKey("projects.id_project"), nullable=True)  # Liên kết thẳng đến project
    feedback_content = Column(Text)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Release(Base):
    __tablename__ = "releases"
    id_release = Column(Integer, primary_key=True, autoincrement=True)
    id_version = Column(Integer, ForeignKey("code_versions.id_version"))
    zip_url = Column(String(500))
    documentation_url = Column(String(500))
    released_at = Column(DateTime, default=datetime.utcnow)
