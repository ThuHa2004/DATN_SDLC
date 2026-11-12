import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext
import os
from dotenv import load_dotenv

# Cấu hình mã hóa bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Cấu hình chuỗi bí mật cho JWT (Trong thực tế nên để ở file .env)
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or not SECRET_KEY.strip():
    raise RuntimeError("Missing required environment variable SECRET_KEY.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # Token sống 1 ngày

def verify_password(plain_password, hashed_password):
    """Hàm kiểm tra so khớp mật khẩu"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Hàm băm mật khẩu trước khi lưu DB"""
    return pwd_context.hash(password)

def create_access_token(data: dict):
    """Hàm sinh JWT Token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.core.database import SessionLocal
from app.models.user import User

# Khai báo cấu trúc bóc tách Bearer Token từ Header của request
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def get_db_security():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ĐÂY CHÍNH LÀ HÀM NGƯỜI GÁC CỔNG
def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db_security)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Giải mã token bằng SECRET_KEY và ALGORITHM đã khai báo ở trên
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # Tìm user trong Database
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user