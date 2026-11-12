from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"
    id_chat = Column(Integer, primary_key=True, autoincrement=True)
    id_project = Column(String(36), ForeignKey("projects.id_project"))
    sender_role = Column(String(20))  # USER / BA_AGENT / SYSTEM / ORCHESTRATOR
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class AgentLog(Base):
    __tablename__ = "agent_logs"
    id_log = Column(Integer, primary_key=True, autoincrement=True)
    id_project = Column(String(36), ForeignKey("projects.id_project"))
    agent_name = Column(String(50))
    action_detail = Column(Text)
    status = Column(String(20))        # STARTED / SUCCESS / FAILED
    correlation_id = Column(String(36), nullable=True)  # UUID để nhóm các log cùng 1 pipeline run
    created_at = Column(DateTime, default=datetime.utcnow)
