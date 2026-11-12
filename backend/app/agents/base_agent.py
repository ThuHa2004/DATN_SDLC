from app.services.gemini_service import generate_text

class BaseAgent:
    # BƯỚC 1: Thêm tham số model_name mặc định là deepseek-chat
    def __init__(self, name: str, role_description: str, model_name: str = "deepseek-chat"):
        self.name = name
        self.role_description = role_description
        self.model_name = model_name

    async def execute(self, user_input: str, context: str = "") -> str:
        """Tách biệt System Prompt (vai trò) và User Prompt (ngữ cảnh + yêu cầu) cho DeepSeek"""
        
        # BƯỚC 2: Loại bỏ vai trò (role) ra khỏi chuỗi gộp, chỉ gộp context và user_input
        if context:
            full_prompt = f"Ngữ cảnh dự án hiện tại:\n{context}\n\nYêu cầu từ người dùng:\n{user_input}\n\nDựa vào vai trò của bạn, hãy đưa ra phản hồi phù hợp nhất."
        else:
            full_prompt = user_input

        # BƯỚC 3: Truyền riêng role_description vào tham số system_prompt
        response = await generate_text(
            prompt=full_prompt,
            model_name=self.model_name,
            system_prompt=self.role_description
        )
        return response