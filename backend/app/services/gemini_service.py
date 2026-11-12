import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import os

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

load_dotenv()

# Khởi tạo client OpenAI nhưng trỏ base_url về máy chủ của DeepSeek
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key or not api_key.strip():
    raise RuntimeError("Missing required environment variable DEEPSEEK_API_KEY.")

client = AsyncOpenAI(
    api_key=api_key, 
    base_url="https://api.deepseek.com"
)

async def generate_text(prompt: str, model_name: str = "deepseek-chat", system_prompt: str = "") -> str:
    """Hàm giao tiếp với DeepSeek API"""
    try:
        messages = []
        # Nếu Agent có role/system_prompt, đưa vào mảng messages
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Đưa yêu cầu của người dùng vào
        messages.append({"role": "user", "content": prompt})

        # Gọi API bất đồng bộ
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2, # Giữ temperature thấp để code sinh ra ổn định, ít ảo giác
            max_tokens=8000  # DeepSeek hỗ trợ max_tokens khá lớn
        )
        if response.choices[0].finish_reason == "length":
            raise RuntimeError("Model output was truncated; reduce module scope or retry generation")
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Model returned an empty response")
        return content
        
    except Exception as exc:
        raise RuntimeError("LLM generation failed; inspect provider connectivity/quota or output size") from exc
