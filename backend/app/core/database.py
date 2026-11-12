import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# Lấy biến môi trường, nếu không tìm thấy file .env thì dùng luôn chuỗi kết nối mặc định
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://admin:admin2004@localhost:5433/sdlc_db"
)

# Tạo engine kết nối tới PostgreSQL
engine = create_engine(DATABASE_URL)

# Tạo phiên làm việc (Session)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base model để các bảng khác kế thừa
Base = declarative_base()