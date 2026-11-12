from sqlalchemy import Column, Integer, String #NVARCHAR #(THÊM NVARCHAR)
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id_user = Column(Integer, primary_key=True, index=True, autoincrement=True)
    #user_name = Column(NVARCHAR(100), nullable=False)
    user_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="USER")