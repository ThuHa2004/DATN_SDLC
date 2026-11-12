"""
Module Service: Các hàm CRUD để quản lý trạng thái Module, ModuleAttempt,
TestExecution và SourceFile trong database.

Mục đích: Tách biệt logic DB khỏi Orchestrator để pipeline có thể
persist state và resume sau khi server restart hoặc request timeout.
"""
import json
import hashlib
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.module import Module, ModuleDependency, ModuleAttempt
from app.models.testing import TestExecution
from app.models.code_version import SourceFile, CodeVersion
from app.services.json_utils import extract_pure_json, _extract_pure_json


# ==============================================================================
# MODULE CRUD
# ==============================================================================

def create_modules_from_design(db: Session, id_design: int, design_obj: dict) -> list[Module]:
    """
    Đọc JSON từ Design Agent, tạo bản ghi Module và ModuleDependency trong DB.
    Trả về danh sách Module đã được sắp xếp theo topological order.
    """
    raw_modules = design_obj.get("architecture_modules", [])
    
    # Topological sort để xác định thứ tự chạy
    sorted_modules = _topological_sort(raw_modules)
    
    db_modules: list[Module] = []
    module_key_to_id: dict[str, int] = {}

    for order_idx, raw in enumerate(sorted_modules):
        module = Module(
            id_design=id_design,
            module_key=raw.get("module_id", f"module_{order_idx}"),
            module_name=raw.get("module_id", f"Module {order_idx}"),
            description=raw.get("description", ""),
            module_type=raw.get("layer", "UNKNOWN"),
            module_order=order_idx,
            specification=json.dumps(raw, ensure_ascii=False),
            status="PENDING",
            retry_count=0,
            max_retries=3,
            is_testable=raw.get("is_testable", True),
        )
        db.add(module)
        db.flush()  # Lấy id_module ngay sau khi insert

        db_modules.append(module)
        module_key_to_id[raw.get("module_id", "")] = module.id_module

    # Tạo các cạnh dependency sau khi tất cả module đã có id
    for order_idx, raw in enumerate(sorted_modules):
        module_id = module_key_to_id.get(raw.get("module_id", ""))
        for dep_key in raw.get("dependencies", []):
            dep_id = module_key_to_id.get(dep_key)
            if dep_id and module_id:
                dep = ModuleDependency(
                    id_module=module_id,
                    depends_on_module_id=dep_id,
                    id_design=id_design,
                )
                db.add(dep)

    db.commit()
    return db_modules


def get_pending_modules(db: Session, id_design: int) -> list[Module]:
    """Lấy danh sách module chưa hoàn thành, sắp xếp theo thứ tự chạy."""
    return (
        db.query(Module)
        .filter(Module.id_design == id_design, Module.status.in_(["PENDING", "FAILED"]))
        .order_by(Module.module_order)
        .all()
    )


def get_all_modules(db: Session, id_design: int) -> list[Module]:
    """Lấy tất cả module theo thứ tự chạy."""
    return (
        db.query(Module)
        .filter(Module.id_design == id_design)
        .order_by(Module.module_order)
        .all()
    )


def set_module_status(db: Session, module: Module, status: str):
    """Cập nhật trạng thái module và ghi vào DB ngay lập tức."""
    module.status = status
    module.updated_at = datetime.utcnow()
    db.commit()


def get_completed_interfaces(db: Session, id_design: int) -> dict:
    """
    Lấy danh sách interface (hàm/class đã export) của tất cả module đã PASSED.
    Dùng để cung cấp context cho Dev Agent khi sinh module tiếp theo.
    """
    passed_modules = (
        db.query(Module)
        .filter(Module.id_design == id_design, Module.status == "PASSED")
        .order_by(Module.module_order)
        .all()
    )
    interfaces = {}
    for m in passed_modules:
        try:
            spec = json.loads(m.specification)
            exported = []
            for f in spec.get("files", []):
                exported.extend(f.get("exported_interfaces", []))
            interfaces[m.module_key] = exported
        except Exception:
            interfaces[m.module_key] = []
    return interfaces


def get_completed_code_context(db: Session, id_design: int, project_id: str = None) -> str:
    """
    Đọc mã nguồn thực tế của các module đã PASSED trong sandbox hoặc DB
    để Dev Agent và Testing Agent biết chính xác chữ ký hàm, class, constructor
    của các tầng trước (Models, Repositories, Services) tránh lỗi inject sai dependencies.
    """
    from app.services.file_service import source_context
    if project_id:
        # Include actual generated dependencies even if a preceding unit test failed.
        return source_context(project_id)
    return json.dumps(get_completed_interfaces(db, id_design), ensure_ascii=False)


# ==============================================================================
# MODULE ATTEMPT CRUD
# ==============================================================================

def create_attempt(db: Session, id_module: int, attempt_number: int, attempt_type: str) -> ModuleAttempt:
    """Tạo bản ghi ModuleAttempt khi Dev Agent bắt đầu một lần thử."""
    attempt = ModuleAttempt(
        id_module=id_module,
        attempt_number=attempt_number,
        attempt_type=attempt_type,
        status="RUNNING",
        started_at=datetime.utcnow(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def finish_attempt(db: Session, attempt: ModuleAttempt, status: str, error_summary: str = "", source_revision: str = ""):
    """Cập nhật kết quả của một lần thử."""
    attempt.status = status
    attempt.error_summary = error_summary[:2000] if error_summary else ""  # Giới hạn 2000 ký tự
    attempt.source_revision = source_revision
    attempt.finished_at = datetime.utcnow()
    db.commit()


# ==============================================================================
# TEST EXECUTION CRUD
# ==============================================================================

def create_test_execution(
    db: Session,
    id_module: int,
    id_attempt: int,
    id_version: int | None,
    test_type: str = "UNIT",
) -> TestExecution:
    """Tạo bản ghi TestExecution khi bắt đầu chạy test."""
    execution = TestExecution(
        id_module=id_module,
        id_attempt=id_attempt,
        id_version=id_version,
        test_type=test_type,
        status="RUNNING",
        total_tests=0,
        passed_tests=0,
        failed_tests=0,
        skipped_tests=0,
        started_at=datetime.utcnow(),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def finish_test_execution(
    db: Session,
    execution: TestExecution,
    status: str,
    total: int = 0,
    passed: int = 0,
    failed: int = 0,
    skipped: int = 0,
    error_logs: str = "",
):
    """Cập nhật kết quả sau khi test chạy xong."""
    execution.status = status
    execution.total_tests = total
    execution.passed_tests = passed
    execution.failed_tests = failed
    execution.skipped_tests = skipped
    execution.error_logs = error_logs[:5000] if error_logs else ""  # Giới hạn 5000 ký tự
    execution.finished_at = datetime.utcnow()
    db.commit()


def parse_pytest_output(log_output: str) -> dict:
    """Fallback for old executions; prefer the last summary, include collection errors."""
    import re
    result = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "total": 0}
    for key, pattern in (("passed", "passed"), ("failed", "failed"), ("skipped", "skipped"), ("errors", "errors?")):
        matches = re.findall(r"(\d+)\s+" + pattern + r"\b", log_output)
        if matches:
            result[key] = int(matches[-1])
    result["total"] = sum(result[key] for key in ("passed", "failed", "skipped", "errors"))
    return result


def read_test_report(path) -> dict:
    """Read pytest/Vitest/Node JUnit or Jest JSON, including setup errors/skips."""
    from pathlib import Path
    import xml.etree.ElementTree as ET
    path = Path(path)
    stats = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "total": 0}
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        stats.update(total=data.get("numTotalTests", 0), passed=data.get("numPassedTests", 0),
                     failed=data.get("numFailedTests", 0), skipped=data.get("numPendingTests", 0))
        stats["errors"] = data.get("numRuntimeErrorTestSuites", 0)
        return stats
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    for case in cases:
        stats["total"] += 1
        if case.find("failure") is not None:
            stats["failed"] += 1
        elif case.find("error") is not None:
            stats["errors"] += 1
        elif case.find("skipped") is not None:
            stats["skipped"] += 1
        else:
            stats["passed"] += 1
    # Collection/setup errors may be represented only on a suite.
    suites = [suite for suite in root.iter("testsuite") if not list(suite.iter("testsuite"))[1:]]
    stats["errors"] = max(stats["errors"], sum(int(suite.get("errors", 0)) for suite in suites))
    stats["failed"] = max(stats["failed"], sum(int(suite.get("failures", 0)) for suite in suites))
    return stats


def is_test_report_passed(return_code: int, stats: dict, strict: bool = False) -> bool:
    # A process exiting 0 with missing tests or skipped integration checks is not a pass.
    return (return_code == 0 and stats["passed"] > 0 and stats["failed"] == 0
            and stats.get("errors", 0) == 0 and (not strict or stats["skipped"] == 0))


# ==============================================================================
# SOURCE FILE CRUD
# ==============================================================================

def save_source_files(db: Session, id_version: int, id_module: int | None, code_json_str: str):
    """
    Parse JSON code và lưu danh sách SourceFile vào DB.
    Tính checksum SHA256 cho mỗi file để version-lock.
    """
    try:
        code_dict = json.loads(code_json_str)
        for file_obj in code_dict.get("files", []):
            file_path = file_obj.get("file_path", "unknown.txt")
            code_content = file_obj.get("code", "")
            checksum = hashlib.sha256(code_content.encode()).hexdigest()

            db.add(SourceFile(
                id_version=id_version,
                id_module=id_module,
                file_name=file_path,
                file_path=file_path,
                checksum=checksum,
            ))
        db.commit()
    except Exception as e:
        print(f"[module_service] Lỗi lưu source files: {e}")


# ==============================================================================
# INTERNAL HELPERS
# ==============================================================================

def _topological_sort(modules: list) -> list:
    """
    Sắp xếp module theo thứ tự phụ thuộc (Kahn's Algorithm).
    Module không phụ thuộc ai sẽ chạy trước.
    Raises ValueError nếu phát hiện circular dependency.
    """
    keys = [m.get("module_id") for m in modules]
    if not modules or any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Design must contain nonempty, unique module IDs")
    known = set(keys)
    for module in modules:
        missing = set(module.get("dependencies", [])) - known
        if missing:
            raise ValueError(f"Unknown dependencies in {module['module_id']}: {sorted(missing)}")
    resolved, pending = [], modules.copy()
    while pending:
        completed = {module["module_id"] for module in resolved}
        ready = [module for module in pending if set(module.get("dependencies", [])).issubset(completed)]
        if not ready:
            raise ValueError("Circular dependencies in module design")
        for module in ready:
            resolved.append(module)
            pending.remove(module)
    return resolved


def get_project_version(db: Session, project_id: str):
    from app.models.requirement import DesignSpec, SRSRecord, BRDRecord
    return (db.query(CodeVersion).join(DesignSpec, CodeVersion.id_design == DesignSpec.id_design)
            .join(SRSRecord, DesignSpec.id_srs == SRSRecord.id_srs)
            .join(BRDRecord, SRSRecord.id_brd == BRDRecord.id_brd)
            .filter(BRDRecord.id_project == project_id).order_by(CodeVersion.id_version.desc()).first())
