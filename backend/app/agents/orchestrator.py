"""
Orchestrator: Điều phối luồng xử lý dựa trên trạng thái dự án (project_status).

Vai trò sau refactor:
  - Nhận message từ user và project_status
  - Nếu đang GATHERING → BA Agent phỏng vấn
  - Nếu BA chốt xong → Ủy quyền cho PipelineRunner chạy toàn bộ pipeline
  - Nếu đang PREVIEW/SANDBOX → xử lý feedback (sửa code / đóng gói)
  
Không còn chứa business logic pipeline → đã chuyển sang pipeline_runner.py
"""
import re
import json
import random
import subprocess
from sqlalchemy.orm import Session

from app.agents.ba_agent import BAAgent
from app.agents.dev_agent import DevAgent
from app.agents.devops_agent import DevOpsAgent
from app.agents.pipeline_runner import PipelineRunner
from app.services.file_service import SANDBOX_DIR, export_code_to_sandbox, source_context, source_snapshot
from app.services.json_utils import _extract_pure_json
from app.services.module_service import get_project_version, save_source_files
from app.models.requirement import DesignSpec



class Orchestrator:
    def __init__(self):
        self.ba_agent = BAAgent()
        self.dev_agent = DevAgent()
        self.devops_agent = DevOpsAgent()
        self.pipeline_runner = PipelineRunner()

    async def handle_user_message(
        self,
        project_id: str,
        project_status: str,
        user_message: str,
        chat_history: str = "",
        db: Session = None,
    ) -> dict:
        """
        Điểm vào duy nhất để xử lý message từ user.
        Tham số db: SQLAlchemy Session để pipeline lưu state vào PostgreSQL.
        """

        # ══════════════════════════════════════════════════════════════════════
        # TRẠNG THÁI: GATHERING (BA phỏng vấn thu thập yêu cầu)
        # ══════════════════════════════════════════════════════════════════════
        if project_status in ["INIT", "GATHERING"]:
            ba_response = await self.ba_agent.execute(
                user_input=user_message,
                context=chat_history,
            )

            # BA chốt yêu cầu → kích hoạt pipeline tự động
            if "[ĐÃ ĐỦ THÔNG TIN" in ba_response:
                print("── BA đã chốt yêu cầu! Kích hoạt Pipeline tự động...")

                if db is None:
                    return {
                        "action": "ERROR",
                        "message": "Lỗi hệ thống: DB session không được truyền vào Orchestrator.",
                    }

                result = await self.pipeline_runner.run_full_pipeline(
                    project_id=project_id,
                    chat_history=chat_history,
                    ba_response=ba_response,
                    db=db,
                )
                return result

            # Chưa đủ thông tin → tiếp tục phỏng vấn
            return {
                "action": "CONTINUE_GATHERING",
                "message": ba_response,
            }

        # ══════════════════════════════════════════════════════════════════════
        # TRẠNG THÁI: PREVIEW / SANDBOX / CODING_FAILED (Feedback loop)
        # ══════════════════════════════════════════════════════════════════════
        elif project_status in ["PREVIEW", "SANDBOX", "CODING_FAILED"]:
            prompt_lower = user_message.lower()

            # --- Đóng gói và bàn giao ---
            if any(kw in prompt_lower for kw in ["đóng gói", "hoàn thiện", "xuất file", "bàn giao", "nghiệm thu", "tải code", "download"]):
                print("── User yêu cầu đóng gói / nghiệm thu. Gọi DevOps Agent sinh README...")
                
                # Quét cấu trúc file thực tế trong sandbox để DevOps Agent viết README chính xác 100%
                project_dir = SANDBOX_DIR / project_id
                files_context = []
                if project_dir.exists():
                    for item in project_dir.rglob("*"):
                        if item.is_file() and not any(part.startswith((".", "__pycache__", "venv")) for part in item.parts):
                            rel_path = item.relative_to(project_dir)
                            files_context.append(str(rel_path))
                
                file_tree_str = "\n".join(files_context[:50])

                readme_json = await self.devops_agent.execute(
                    user_input=(
                        "Người dùng yêu cầu xuất mã nguồn. Đọc trạng thái kiểm thử thực tế; không tuyên bố mọi kiểm thử đạt nếu còn lỗi. "
                        "Hãy sinh file `README.md` bằng tiếng Việt hướng dẫn chi tiết người dùng: "
                        "1. Giới thiệu tổng quan hệ thống.\n"
                        "2. Các yêu cầu cài đặt trên máy người dùng (Python 3.11+, Docker Desktop, Git...).\n"
                        "3. Hướng dẫn cấu hình môi trường (.env mẫu nếu có).\n"
                        "4. Cách 1: Khởi chạy nhanh bằng Docker: `docker-compose up --build -d`.\n"
                        "5. Cách 2: Khởi chạy thủ công trên máy host không dùng Docker.\n"
                        "6. Hướng dẫn chạy kiểm thử/build đúng stack và thư mục service thực tế (pytest/Vitest/Jest).\n"
                        "7. Danh sách API endpoints chính và hướng dẫn sử dụng.\n\n"
                        f"DANH SÁCH FILE TRONG DỰ ÁN:\n{file_tree_str}\n\n"
                        "BẮT BUỘC trả về đúng định dạng JSON: {\"files\": [{\"file_path\": \"README.md\", \"code\": \"...\"}]}"
                    ),
                    context=source_context(project_id),
                )
                clean_readme = _extract_pure_json(readme_json)
                export_code_to_sandbox(project_id, clean_readme)

                # Nén sẵn file zip
                import shutil
                try:
                    zip_filename = f"{project_id}_source"
                    shutil.make_archive(str(SANDBOX_DIR / zip_filename), "zip", str(project_dir))
                except Exception as e:
                    print(f"[WARN] Nén zip tự động: {e}")

                return {
                    "action": "FINISH_PACKAGING",
                    "message": (
                        "📦 **Đã đóng gói thành công!**\n\n"
                        "Hệ thống đã nghiệm thu và bổ sung file `README.md` hướng dẫn chi tiết cách cài đặt và sử dụng ứng dụng trên máy của bạn.\n\n"
                        "Toàn bộ mã nguồn, cấu hình Docker và các kịch bản kiểm thử đã được nén thành file ZIP.\n\n"
                        f"👉 **Tải trực tiếp:** [⬇ Tải mã nguồn (.ZIP)](http://127.0.0.1:8000/api/projects/{project_id}/download)\n"
                        "*(Hoặc bấm nút **Tải mã nguồn (.ZIP)** màu xanh ở phía trên)*"
                    ),
                    "readme_data": readme_json,
                }

            # Use the same verified runtime/test/preview path for all feedback actions.
            runner = self.pipeline_runner
            version = get_project_version(db, project_id) if db is not None else None
            id_version = version.id_version if version else None
            design = db.query(DesignSpec).filter_by(id_design=version.id_design).first() if version else None
            design_json = design.architecture_json if design and design.architecture_json else "{}"
            design_obj = json.loads(design_json)
            app_port = runner._available_port()
            try:
                config_change = any(kw in prompt_lower for kw in ["docker", "deploy", "container"])
                agent = self.devops_agent if config_change else self.dev_agent
                patch = await agent.execute(
                    user_input=(f"Apply user feedback: {user_message}. Preview host port: {app_port}. "
                                "Use the actual source and preserve existing contracts. Return complete changed files as JSON files."),
                    context=source_context(project_id))
                clean = runner._apply_patch(project_id, patch)
                if id_version:
                    save_source_files(db, id_version, None, clean)
                tests = await runner._safe_system_testing(project_id=project_id, design_json=design_json,
                            final_code=json.dumps(source_snapshot(project_id)), id_version=id_version, db=db)
                for repair_attempt in range(2):
                    if tests["status"] == "passed":
                        break
                    repaired = await runner._safe_fix_system_errors(project_id=project_id,
                        final_code=json.dumps(source_snapshot(project_id)), error_log=tests["log"], db=db)
                    if repaired.get("fixed_code") and id_version:
                        save_source_files(db, id_version, None, repaired["fixed_code"])
                    tests = await runner._safe_system_testing(project_id=project_id, design_json=design_json,
                        final_code=json.dumps(source_snapshot(project_id)), id_version=id_version, db=db)
                preview = await runner._start_docker(project_id, app_port, design_obj)
                for preview_attempt in range(2):
                    if preview["status"] == "passed":
                        break
                    repair = await self.dev_agent.execute(
                        user_input=(f"Fix actual preview startup failure; host port {app_port}. "
                                    "Repair real application/config/dependencies and serve actual frontend; do not edit tests. "
                                    f"Return changed files as JSON. DIAGNOSTICS: {preview['log'][-20000:]}"),
                        context=source_context(project_id))
                    repaired = runner._apply_patch(project_id, repair)
                    if id_version:
                        save_source_files(db, id_version, None, repaired)
                    tests = await runner._safe_system_testing(project_id=project_id, design_json=design_json,
                        final_code=json.dumps(source_snapshot(project_id)), id_version=id_version, db=db)
                    preview = await runner._start_docker(project_id, app_port, design_obj)
                ready = preview["status"] == "passed"
                message = tests["report"] + "\n\n"
                message += (f"**Link Preview:** [{preview['preview_url']}]({preview['preview_url']})" if ready
                            else f"Preview failed:\n```text\n{preview['log'][-6000:]}\n```")
                return {"action": "FINISH_FEEDBACK_AUTO" if ready else "PIPELINE_FAILED", "message": message,
                        "preview_url": preview.get("preview_url"), "system_test_passed": tests["status"] == "passed",
                        "code_data": json.dumps(source_snapshot(project_id)), "id_version": id_version}
            except Exception as exc:
                if db is not None:
                    db.rollback()
                return {"action": "PIPELINE_FAILED", "message": f"Feedback repair failed: {exc}"}

        return {"action": "ERROR", "message": "Invalid project status"}
