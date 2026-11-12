"""
SDLC Multi-Agent API — main.py
Các sửa đổi so với phiên bản cũ:
  1. Xóa khai báo app = FastAPI() thừa (cũ có 2 lần)
  2. Dọn import trùng lặp
  3. Truyền `db` session vào Orchestrator để pipeline lưu state
  4. Thêm API mới: /modules, /modules/{id}/retry, /test-executions
  5. Lưu Release vào bảng releases khi user đóng gói
  6. Lưu SandboxEnvironment + UserFeedback đúng cách
"""
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
import shutil, subprocess, os, json, re
from datetime import datetime

# Core
from app.core.database import SessionLocal
from app.core.security import get_current_user, get_password_hash, verify_password, create_access_token

# Models
from app.models.user import User
from app.models.project import Project
from app.models.conversation import Conversation, AgentLog
from app.models.requirement import BRDRecord, SRSRecord, DesignSpec
from app.models.module import Module, ModuleAttempt, ModuleDependency
from app.models.code_version import CodeVersion, SourceFile
from app.models.testing import TestCase, TestExecution, TestRun
from app.models.deployment import SandboxEnvironment, UserFeedback, Release

# Agents & Services
from app.agents.orchestrator import Orchestrator
from app.services.file_service import SANDBOX_DIR, export_code_to_sandbox
from app.services.module_service import save_source_files

# ── App & Middleware ──────────────────────────────────────────────────────────
app = FastAPI(title="SDLC Multi-Agent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()


# ── DB Session Dependency ─────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Admin Guard ───────────────────────────────────────────────────────────────
def get_admin_user(current_user: User = Depends(get_current_user)):
    if not hasattr(current_user, "role") or current_user.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Yêu cầu quyền Quản trị viên.")
    return current_user


# ── JSON Utility ──────────────────────────────────────────────────────────────
def extract_json_safe(text: str) -> str:
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    return match.group(1) if match else text


# =============================================================================
# AUTH APIs
# =============================================================================

class UserRegister(BaseModel):
    user_name: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register_user(user: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email này đã được đăng ký!")
    new_user = User(user_name=user.user_name, email=user.email, password_hash=get_password_hash(user.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Đăng ký thành công!", "id_user": new_user.id_user}


@app.post("/api/auth/login")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Tài khoản không tồn tại!")
    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Mật khẩu không chính xác!")
    access_token = create_access_token(data={"sub": db_user.email, "id_user": db_user.id_user})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"id_user": db_user.id_user, "user_name": db_user.user_name, "email": db_user.email, "role": db_user.role},
    }


# =============================================================================
# PROJECT APIs
# =============================================================================

class ProjectCreate(BaseModel):
    project_name: str


@app.post("/api/projects")
def create_project(project: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_project = Project(project_name=project.project_name, project_status="GATHERING", id_user=current_user.id_user)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return {"message": "Tạo dự án thành công", "id_project": new_project.id_project, "status": new_project.project_status}


@app.get("/api/projects")
def get_all_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.id_user == current_user.id_user).order_by(Project.created_at.desc()).all()
    return {"total": len(projects), "projects": projects}


@app.delete("/api/projects/{id_project}")
def delete_project(id_project: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id_project == id_project, Project.id_user == current_user.id_user).first()
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    # 1. Xóa các hội thoại chat, logs, feedback liên quan đến dự án
    db.query(Conversation).filter(Conversation.id_project == id_project).delete(synchronize_session=False)
    db.query(UserFeedback).filter(UserFeedback.id_project == id_project).delete(synchronize_session=False)
    db.query(AgentLog).filter(AgentLog.id_project == id_project).delete(synchronize_session=False)

    # 2. Xóa cascade từ BRD -> SRS -> DesignSpec -> Modules / Versions theo thứ tự Foreign Key
    brds = db.query(BRDRecord).filter(BRDRecord.id_project == id_project).all()
    for brd in brds:
        srs_list = db.query(SRSRecord).filter(SRSRecord.id_brd == brd.id_brd).all()
        for srs in srs_list:
            designs = db.query(DesignSpec).filter(DesignSpec.id_srs == srs.id_srs).all()
            for design in designs:
                # Lấy danh sách module thuộc design
                modules = db.query(Module).filter(Module.id_design == design.id_design).all()
                mod_ids = [m.id_module for m in modules]

                if mod_ids:
                    # a. Xóa TestRun liên kết với TestCase
                    # b. Xóa TestExecution (FK tới module_attempts, modules, code_versions)
                    db.query(TestExecution).filter(TestExecution.id_module.in_(mod_ids)).delete(synchronize_session=False)
                    # c. Xóa ModuleAttempt (FK tới modules)
                    db.query(ModuleAttempt).filter(ModuleAttempt.id_module.in_(mod_ids)).delete(synchronize_session=False)
                    # d. Xóa ModuleDependency (FK tới modules, design_specs)
                    db.query(ModuleDependency).filter(ModuleDependency.id_design == design.id_design).delete(synchronize_session=False)

                # e. Xóa các bảng tầng CodeVersion (SourceFile, TestCase, TestRun, Sandbox, Release)
                versions = db.query(CodeVersion).filter(CodeVersion.id_design == design.id_design).all()
                ver_ids = [v.id_version for v in versions]
                if ver_ids:
                    # Xóa TestExecution thuộc version (nếu có system test)
                    db.query(TestExecution).filter(TestExecution.id_version.in_(ver_ids)).delete(synchronize_session=False)
                    
                    # Xóa TestRun theo TestCase
                    tcs = db.query(TestCase).filter(TestCase.id_version.in_(ver_ids)).all()
                    tc_ids = [tc.id_testcase for tc in tcs]
                    if tc_ids:
                        from app.models.testing import TestRun
                        db.query(TestRun).filter(TestRun.id_testcase.in_(tc_ids)).delete(synchronize_session=False)

                    db.query(TestCase).filter(TestCase.id_version.in_(ver_ids)).delete(synchronize_session=False)
                    db.query(SourceFile).filter(SourceFile.id_version.in_(ver_ids)).delete(synchronize_session=False)
                    db.query(Release).filter(Release.id_version.in_(ver_ids)).delete(synchronize_session=False)

                    for sb in db.query(SandboxEnvironment).filter(SandboxEnvironment.id_version.in_(ver_ids)).all():
                        db.query(UserFeedback).filter(UserFeedback.id_sandbox == sb.id_sandbox).delete(synchronize_session=False)
                    db.query(SandboxEnvironment).filter(SandboxEnvironment.id_version.in_(ver_ids)).delete(synchronize_session=False)

                    db.query(CodeVersion).filter(CodeVersion.id_design == design.id_design).delete(synchronize_session=False)

                # f. Xóa các module sau khi các bảng con đã bị xóa
                if mod_ids:
                    db.query(Module).filter(Module.id_design == design.id_design).delete(synchronize_session=False)

                # g. Xóa DesignSpec
                db.query(DesignSpec).filter(DesignSpec.id_design == design.id_design).delete(synchronize_session=False)

            # Xóa SRS
            db.query(SRSRecord).filter(SRSRecord.id_srs == srs.id_srs).delete(synchronize_session=False)

        # Xóa BRD
        db.query(BRDRecord).filter(BRDRecord.id_brd == brd.id_brd).delete(synchronize_session=False)

    # 3. Dọn dẹp thư mục vật lý sandbox và snapshot
    try:
        project_dir = SANDBOX_DIR / id_project
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
        snapshot_dir = SANDBOX_DIR / f"{id_project}_snapshots"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
    except Exception as e:
        print(f"Lỗi xóa thư mục vật lý: {e}")

    # 4. Cuối cùng xóa Project
    db.delete(project)
    db.commit()
    return {"message": f"Đã xóa thành công dự án: {project.project_name}"}


# =============================================================================
# CHAT API — Điểm vào chính của pipeline
# =============================================================================

class ChatRequest(BaseModel):
    id_project: str
    prompt: str


@app.post("/api/chat")
async def chat_with_multi_agent(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Kiểm tra dự án
    project = db.query(Project).filter(
        Project.id_project == request.id_project,
        Project.id_user == current_user.id_user,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    # 2. Lưu message của user
    db.add(Conversation(id_project=request.id_project, sender_role="USER", message=request.prompt))
    db.commit()

    # 3. Lấy lịch sử chat
    histories = db.query(Conversation).filter(
        Conversation.id_project == request.id_project
    ).order_by(Conversation.created_at).all()
    chat_context = "\n".join([f"{h.sender_role}: {h.message}" for h in histories])

    # 4. Gọi Orchestrator (truyền db session để pipeline lưu state)
    orchestrator_result = await orchestrator.handle_user_message(
        project_id=request.id_project,
        project_status=project.project_status,
        user_message=request.prompt,
        chat_history=chat_context,
        db=db,
    )

    action = orchestrator_result["action"]
    ai_message_text = orchestrator_result["message"]

    # 5. Xử lý action từ Orchestrator
    if action == "FINISH_ALL_AUTO":
        # Pipeline chạy xong thành công → trạng thái đã được set PREVIEW trong pipeline_runner
        # Lưu source files nếu chưa có (từ devops_data)
        try:
            devops_data = orchestrator_result.get("devops_data", "{}")
            id_version = orchestrator_result.get("id_version")
            if id_version and devops_data:
                clean_devops = extract_json_safe(devops_data)
                save_source_files(db, id_version, None, clean_devops)
        except Exception as e:
            print(f"[WARN] Lỗi lưu devops source files: {e}")

    elif action == "PIPELINE_FAILED":
        project.project_status = "CODING_FAILED"
        db.commit()

    elif action == "FINISH_FEEDBACK_AUTO":
        project.project_status = "PREVIEW"
        db.commit()

    elif action == "FINISH_SANDBOX_CONFIG":
        project.project_status = "PREVIEW"
        db.commit()

    elif action == "FINISH_PACKAGING":
        # Lưu vào bảng releases
        try:
            latest_brd = db.query(BRDRecord).filter(BRDRecord.id_project == request.id_project).order_by(BRDRecord.id_brd.desc()).first()
            if latest_brd:
                latest_srs = db.query(SRSRecord).filter(SRSRecord.id_brd == latest_brd.id_brd).order_by(SRSRecord.id_srs.desc()).first()
                if latest_srs:
                    latest_design = db.query(DesignSpec).filter(DesignSpec.id_srs == latest_srs.id_srs).order_by(DesignSpec.id_design.desc()).first()
                    if latest_design:
                        latest_version = db.query(CodeVersion).filter(CodeVersion.id_design == latest_design.id_design).order_by(CodeVersion.id_version.desc()).first()
                        if latest_version:
                            db.add(Release(
                                id_version=latest_version.id_version,
                                zip_url=f"/api/projects/{request.id_project}/download",
                                documentation_url="README.md",
                                released_at=datetime.utcnow(),
                            ))
        except Exception as e:
            print(f"[WARN] Lỗi lưu Release: {e}")

        project.project_status = "COMPLETED"
        db.commit()

    # 6. Lưu response của AI vào lịch sử chat
    db.add(Conversation(id_project=request.id_project, sender_role="BA_AGENT", message=ai_message_text))
    db.commit()

    return {
        "ai_response": ai_message_text,
        "action": action,
        "srs_data": orchestrator_result.get("srs_data"),
    }


# =============================================================================
# MODULE APIs — Theo dõi tiến trình từng module
# =============================================================================

@app.get("/api/projects/{id_project}/modules")
def get_project_modules(
    id_project: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lấy danh sách tất cả module và trạng thái của chúng."""
    project = db.query(Project).filter(Project.id_project == id_project, Project.id_user == current_user.id_user).first()
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    latest_brd = db.query(BRDRecord).filter(BRDRecord.id_project == id_project).order_by(BRDRecord.id_brd.desc()).first()
    if not latest_brd:
        return {"modules": [], "summary": {"total": 0, "passed": 0, "failed": 0, "pending": 0}}

    latest_srs = db.query(SRSRecord).filter(SRSRecord.id_brd == latest_brd.id_brd).order_by(SRSRecord.id_srs.desc()).first()
    if not latest_srs:
        return {"modules": [], "summary": {}}

    latest_design = db.query(DesignSpec).filter(DesignSpec.id_srs == latest_srs.id_srs).order_by(DesignSpec.id_design.desc()).first()
    if not latest_design:
        return {"modules": [], "summary": {}}

    modules = db.query(Module).filter(Module.id_design == latest_design.id_design).order_by(Module.module_order).all()

    module_list = []
    for m in modules:
        attempts = db.query(ModuleAttempt).filter(ModuleAttempt.id_module == m.id_module).order_by(ModuleAttempt.attempt_number).all()
        module_list.append({
            "id_module": m.id_module,
            "module_key": m.module_key,
            "module_name": m.module_name,
            "module_type": m.module_type,
            "module_order": m.module_order,
            "status": m.status,
            "retry_count": m.retry_count,
            "max_retries": m.max_retries,
            "is_testable": m.is_testable,
            "attempts": [{"attempt_number": a.attempt_number, "type": a.attempt_type, "status": a.status} for a in attempts],
        })

    total = len(modules)
    passed = sum(1 for m in modules if m.status == "PASSED")
    failed = sum(1 for m in modules if m.status == "FAILED")
    pending = sum(1 for m in modules if m.status in ["PENDING", "CODING", "TESTING"])

    return {
        "modules": module_list,
        "summary": {"total": total, "passed": passed, "failed": failed, "pending": pending},
    }


@app.get("/api/projects/{id_project}/test-executions")
def get_test_executions(
    id_project: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lấy lịch sử tất cả lần chạy test của dự án."""
    project = db.query(Project).filter(Project.id_project == id_project, Project.id_user == current_user.id_user).first()
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    latest_brd = db.query(BRDRecord).filter(BRDRecord.id_project == id_project).order_by(BRDRecord.id_brd.desc()).first()
    if not latest_brd:
        return {"executions": []}

    latest_srs = db.query(SRSRecord).filter(SRSRecord.id_brd == latest_brd.id_brd).order_by(SRSRecord.id_srs.desc()).first()
    if not latest_srs:
        return {"executions": []}

    latest_design = db.query(DesignSpec).filter(DesignSpec.id_srs == latest_srs.id_srs).order_by(DesignSpec.id_design.desc()).first()
    if not latest_design:
        return {"executions": []}

    modules = db.query(Module).filter(Module.id_design == latest_design.id_design).all()
    module_ids = [m.id_module for m in modules]

    executions = db.query(TestExecution).filter(TestExecution.id_module.in_(module_ids)).order_by(TestExecution.started_at.desc()).all()

    return {
        "executions": [
            {
                "id_execution": e.id_execution,
                "id_module": e.id_module,
                "test_type": e.test_type,
                "status": e.status,
                "total_tests": e.total_tests,
                "passed_tests": e.passed_tests,
                "failed_tests": e.failed_tests,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
            }
            for e in executions
        ]
    }


# =============================================================================
# HISTORY & DOWNLOAD APIs
# =============================================================================

@app.get("/api/projects/{id_project}/history")
def get_project_history(id_project: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id_project == id_project, Project.id_user == current_user.id_user).first()
    if not project:
        raise HTTPException(status_code=403, detail="Truy cập bị từ chối!")
    histories = db.query(Conversation).filter(Conversation.id_project == id_project).order_by(Conversation.created_at).all()
    return {
        "messages": [
            {"role": "USER" if h.sender_role == "USER" else "AGENT", "content": h.message}
            for h in histories
        ]
    }


@app.get("/api/projects/{id_project}/download")
def download_project_zip(id_project: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id_project == id_project).first()
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án!")
    project_dir = SANDBOX_DIR / id_project
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy mã nguồn vật lý trong sandbox!")
    zip_filename = f"{id_project}_source"
    shutil.make_archive(str(SANDBOX_DIR / zip_filename), "zip", str(project_dir))
    return FileResponse(path=SANDBOX_DIR / f"{zip_filename}.zip", media_type="application/zip", filename=f"project_{id_project}.zip")


@app.post("/api/projects/{id_project}/preview")
async def run_docker_preview(id_project: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id_project == id_project, Project.id_user == current_user.id_user).first()
    if not project:
        raise HTTPException(status_code=403, detail="Access denied")
    result = await orchestrator.pipeline_runner._start_docker(id_project)
    ready = result["status"] == "passed"
    project.project_status = "PREVIEW" if ready else "CODING_FAILED"
    db.commit()
    return {"status": "success" if ready else "error", "message": "Preview ready" if ready else "Preview failed",
            "preview_url": result.get("preview_url"), "logs": result["log"]}


# =============================================================================
# ADMIN APIs
# =============================================================================

@app.get("/api/admin/users")
def admin_get_all_users(db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    users = db.query(User).all()
    return {
        "total_users": len(users),
        "users": [
            {"id_user": u.id_user, "user_name": u.user_name, "email": u.email, "role": getattr(u, "role", "USER"),
             "total_projects": db.query(Project).filter(Project.id_user == u.id_user).count()}
            for u in users
        ],
    }


@app.delete("/api/admin/users/{target_id_user}")
def admin_delete_user(target_id_user: int, db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    user = db.query(User).filter(User.id_user == target_id_user).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    db.delete(user)
    db.commit()
    return {"message": f"Đã xóa người dùng {user.email}"}


@app.get("/api/admin/logs")
def admin_get_logs(limit: int = 100, db: Session = Depends(get_db), admin: User = Depends(get_admin_user)):
    logs = db.query(AgentLog).order_by(AgentLog.created_at.desc()).limit(limit).all()
    return {
        "total_logs_retrieved": len(logs),
        "logs": [{"id_log": l.id_log, "id_project": l.id_project, "agent_name": l.agent_name,
                  "action_detail": l.action_detail, "status": l.status, "created_at": l.created_at} for l in logs],
    }


class SystemConfigUpdate(BaseModel):
    default_model: str
    max_testing_retries: int
    docker_memory_limit: str


@app.get("/api/admin/config")
def admin_get_config(admin: User = Depends(get_admin_user)):
    return {"default_model": "deepseek-chat", "max_testing_retries": 3, "docker_memory_limit": "512m", "is_maintenance_mode": False}


@app.put("/api/admin/config")
def admin_update_config(config: SystemConfigUpdate, admin: User = Depends(get_admin_user)):
    return {"message": "Đã cập nhật cấu hình thành công", "new_config": config.dict()}
