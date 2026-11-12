"""Persisted SDLC orchestration with per-service tests and verified preview.
Modules run in dependency order with bounded repair attempts. A frozen integration
suite and unit regression report actual failures before a bounded Docker preview
repair cycle. Preview availability and test quality are reported separately.
"""
import json
import re
import asyncio
import urllib.request
import urllib.error
import random
import socket
import time
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import subprocess
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.requirement import BRDRecord, SRSRecord, DesignSpec
from app.models.code_version import CodeVersion
from app.models.module import Module
from app.models.testing import TestExecution
from app.models.project import Project

from app.services.module_service import (
    create_modules_from_design,
    get_all_modules,
    get_pending_modules,
    get_completed_interfaces,
    get_completed_code_context,
    set_module_status,
    save_source_files,
    create_test_execution,
    finish_test_execution,
    parse_pytest_output,
)
from app.services.json_utils import extract_pure_json, _extract_pure_json, merge_code_files
from app.services.file_service import (SANDBOX_DIR, export_code_to_sandbox, source_context, source_snapshot, project_path, is_test_path)

from app.agents.srs_agent import SRSAgent
from app.agents.design_agent import DesignAgent
from app.agents.dev_agent import DevAgent
from app.agents.testing_agent import TestingAgent
from app.agents.devops_agent import DevOpsAgent
from app.agents.module_runner import ModuleRunner, build_test_plans, validate_generated_tests, run_test_plan


class PipelineRunner:
    """
    Chạy toàn bộ pipeline SDLC. Toàn bộ state được lưu vào PostgreSQL.
    Có thể resume từ bất kỳ phase nào nếu server restart.
    """

    def __init__(self):
        self.srs_agent = SRSAgent()
        self.design_agent = DesignAgent()
        self.dev_agent = DevAgent()
        self.testing_agent = TestingAgent()
        self.devops_agent = DevOpsAgent()
        self.module_runner = ModuleRunner()

    # ==========================================================================
    # PHASE 2+3+4: Chạy toàn bộ pipeline sau khi BA chốt yêu cầu
    # ==========================================================================

    async def run_full_pipeline(self, project_id, chat_history, ba_response, db):
        try:
            return await self._run_full_pipeline(project_id, chat_history, ba_response, db)
        except Exception as exc:
            db.rollback()
            return self._error_result("", "", f"Pipeline error: {type(exc).__name__}: {exc}")

    async def _run_full_pipeline(
        self,
        project_id: str,
        chat_history: str,
        ba_response: str,
        db: Session,
    ) -> dict:
        """
        Điểm vào chính sau khi BA Agent xác nhận đã đủ thông tin.
        Trả về dict kết quả để main.py xử lý DB và trả về Frontend.
        """
        project = db.query(Project).filter_by(id_project=project_id).first()

        # ── PHASE 2a: SRS Agent tổng hợp đặc tả ──────────────────────────────
        print("── [PIPELINE 1/5] SRS Agent tổng hợp đặc tả...")
        srs_json = await self.srs_agent.execute(
            user_input="Hãy tổng hợp lịch sử chat thành file JSON đặc tả hệ thống.",
            context=chat_history + f"\nBA_AGENT: {ba_response}",
        )

        # Lưu BRD + SRS vào DB
        new_brd = BRDRecord(id_project=project_id, business_goals="Tóm tắt yêu cầu từ BA Agent")
        db.add(new_brd)
        db.flush()

        new_srs = SRSRecord(id_brd=new_brd.id_brd, functional_specs=srs_json)
        db.add(new_srs)
        db.flush()

        # ── PHASE 2b: Design Agent thiết kế kiến trúc + DAG ──────────────────
        print("── [PIPELINE 2/5] Design Agent thiết kế kiến trúc...")
        design_json = await self.design_agent.execute(
            user_input="Hãy thiết kế kiến trúc hệ thống, database và API dựa trên đặc tả SRS.",
            context=srs_json,
        )
        clean_design_json = _extract_pure_json(design_json)

        ModuleRunner._export(project_id, json.dumps({"files": [
            {"file_path": "SRS.json", "code": _extract_pure_json(srs_json)},
            {"file_path": "design.json", "code": clean_design_json},
        ]}))

        # Lưu DesignSpec + raw JSON kiến trúc
        new_design = DesignSpec(
            id_srs=new_srs.id_srs,
            db_schema=clean_design_json,
            ui_ux_template="Kiến trúc được thiết kế tự động",
            architecture_json=clean_design_json,
        )
        db.add(new_design)
        db.flush()

        # Tạo CodeVersion để gắn SourceFile
        new_version = CodeVersion(id_design=new_design.id_design, version_number="v1.0")
        db.add(new_version)
        db.flush()

        db.commit()

        # ── PHASE 2c: Parse DAG và tạo bản ghi Module trong DB ───────────────
        print("── [PIPELINE 3/5] Phân tích DAG và tạo bảng modules...")
        try:
            design_obj = json.loads(clean_design_json)
        except Exception as e:
            print(f"[LỖI] Không parse được Design JSON: {e}")
            return self._error_result(srs_json, design_json, f"Lỗi parse kiến trúc: {e}")

        try:
            db_modules = create_modules_from_design(db, new_design.id_design, design_obj)
        except ValueError as e:
            return self._error_result(srs_json, design_json, str(e))

        # Lưu module_plan (thứ tự đã sort) vào design_specs
        module_plan = [{"order": m.module_order, "key": m.module_key, "type": m.module_type} for m in db_modules]
        new_design.module_plan = json.dumps(module_plan, ensure_ascii=False)
        db.commit()

        # Tạo design report để hiển thị trên UI
        design_report = self._build_design_report(design_obj)

        # ── PHASE 3: Phát triển từng module theo DAG ─────────────────────────
        print(f"── [PIPELINE 4/5] Bắt đầu phát triển {len(db_modules)} modules...")

        all_test_reports = []
        final_code_data = {"files": []}
        failed_modules = []

        for module in db_modules:
            if module.status == "PASSED":
                print(f"    [SKIP] Module '{module.module_key}' đã PASSED trước đó → bỏ qua.")
                continue

            # Lấy interface và code thực tế của các module đã xong để cung cấp cho Dev & Test Agent
            completed_interfaces = get_completed_code_context(db, new_design.id_design, project_id=project_id)

            print(f"── Module [{module.module_order + 1}/{len(db_modules)}]: '{module.module_key}' ({module.module_type})")

            result = await self.module_runner.run(
                project_id=project_id,
                module=module,
                design_json=clean_design_json,
                completed_interfaces=completed_interfaces,
                id_version=new_version.id_version,
                db=db,
            )

            all_test_reports.append(result["test_report"])

            if result["status"] not in ("passed", "skipped"):
                failed_modules.append(module.module_key)
            final_code_data = json.loads(merge_code_files(
                json.dumps(final_code_data), result["final_code"]))

        # Keep one integration suite throughout the repair cycle; include unit regression.
        system_test_passed = False
        for system_attempt in range(3):
            result = await self._safe_system_testing(
                project_id=project_id, design_json=clean_design_json,
                final_code=json.dumps(final_code_data), id_version=new_version.id_version, db=db)
            all_test_reports.append(result["report"])
            if result["status"] == "passed":
                system_test_passed = True
                break
            if system_attempt < 2:
                fix = await self._safe_fix_system_errors(
                    project_id=project_id, final_code=json.dumps(final_code_data), error_log=result["log"], db=db)
                all_test_reports.append(fix["report"])
                if fix.get("fixed_code"):
                    save_source_files(db, new_version.id_version, None, fix["fixed_code"])
                    final_code_data = json.loads(merge_code_files(json.dumps(final_code_data), fix["fixed_code"]))

        app_port = self._available_port()
        preview = {"status": "failed", "preview_url": None, "log": "Preview not started"}
        devops_json = "{}"
        preview_changed_source = False
        for preview_attempt in range(3):
            try:
                if preview_attempt == 0:
                    devops_json = await self.devops_agent.execute(
                        user_input=(f"Package the ACTUAL application for preview on 127.0.0.1:{app_port}. "
                                    "Return Dockerfile, docker-compose.yml and any required server/proxy config as JSON files. "
                                    "Serve the actual generated frontend, not an API JSON root. "
                                    "Use the exact dependency versions, environment variable types and actual health routes. "
                                    "Include database driver, schema migrations/initialization and same-origin API proxy when required. "
                                    "Do not use fixed container_name or publish database ports. "
                                    "Do not overwrite application source/tests. "
                                    f"DESIGN: {clean_design_json}"), context=source_context(project_id))
                    self._apply_patch(project_id, devops_json)
                    save_source_files(db, new_version.id_version, None, _extract_pure_json(devops_json))
                else:
                    fix = await self.dev_agent.execute(
                        user_input=("Repair PREVIEW STARTUP using the exact log below. Fix the real cause across "
                                    "application/config/dependencies/Dockerfile/compose/proxy. Preserve all existing features and test contracts. "
                                    "Serve the generated frontend and its API; do not substitute a placeholder page. "
                                    "Database schema must exist before requests; settings types and DB drivers must match. "
                                    f"Host preview port must be {app_port}. Return complete changed files as JSON files.\n"
                                    f"PREVIEW DIAGNOSTICS:\n{preview['log'][-20000:]}"), context=source_context(project_id))
                    clean_fix = self._apply_patch(project_id, fix)
                    save_source_files(db, new_version.id_version, None, clean_fix)
                    preview_changed_source = True
                preview = await self._start_docker(project_id, app_port, design_obj)
                if preview["status"] == "passed":
                    break
            except Exception as exc:
                db.rollback()
                preview = {"status": "failed", "preview_url": None, "log": f"{type(exc).__name__}: {exc}"}
        if preview_changed_source:
            # Startup fixes can change application/dependency code: do not retain stale test results.
            result = await self._safe_system_testing(
                project_id=project_id, design_json=clean_design_json,
                final_code=json.dumps(final_code_data), id_version=new_version.id_version, db=db)
            all_test_reports.append(result["report"])
            system_test_passed = result["status"] == "passed"
        if system_test_passed:
            # Every plan runs its complete tests directory. Reconcile previously failed modules
            # only if their generated unit test file exists in that passing regression suite.
            for module in db_modules:
                if module.status == "FAILED":
                    spec = json.loads(module.specification or "{}")
                    candidates = build_test_plans(project_path(project_id), json.dumps({"files": spec.get("files", [])}), module.module_key)
                    if candidates and all((project_path(project_id) / p["target"]).is_file() for p in candidates):
                        set_module_status(db, module, "PASSED")
        failed_modules = [m.module_key for m in db_modules if m.status == "FAILED"]
        actual = source_snapshot(project_id)
        if actual["files"]:
            final_code_data = actual
        preview_ready = preview["status"] == "passed"
        project.project_status = "PREVIEW" if preview_ready else "CODING_FAILED"
        db.commit()
        quality = system_test_passed and not failed_modules
        summary = (f"**SDLC: {'ĐẠT KIỂM THỬ' if quality else 'CẦN TIẾP TỤC SỬA'}**\n\n"
                   f"Module cần sửa: {', '.join(failed_modules) or 'Không có'}. "
                   f"System test + regression: {'PASSED' if system_test_passed else 'FAILED'}.\n\n")
        if preview_ready:
            docker_message = f"**Link Preview:** [{preview['preview_url']}]({preview['preview_url']})"
            if not quality:
                docker_message += "\nPreview dùng để xem và phản hồi; các kiểm thử chưa đạt cần được sửa trước khi nghiệm thu."
        else:
            docker_message = f"**Khởi chạy preview thất bại**\n```text\n{preview['log'][-6000:]}\n```"
        return {"action": "FINISH_ALL_AUTO" if preview_ready else "PIPELINE_FAILED",
                "message": summary + design_report + "\n\n" + "\n\n".join(all_test_reports) + "\n\n" + docker_message,
                "srs_data": srs_json, "design_data": design_json, "code_data": json.dumps(final_code_data),
                "test_data": json.dumps({"system_test_passed": system_test_passed, "failed_modules": failed_modules}),
                "failed_modules": failed_modules, "system_test_passed": system_test_passed,
                "preview_url": preview.get("preview_url"), "quality_passed": quality,
                "devops_data": devops_json, "id_version": new_version.id_version}

    async def _safe_system_testing(self, **kwargs):
        try:
            return await self._run_system_testing(**kwargs)
        except Exception as exc:
            kwargs["db"].rollback()
            return {"status": "failed", "report": f"### System test ERROR\n{exc}", "log": str(exc)}

    async def _safe_fix_system_errors(self, **kwargs):
        try:
            return await self._fix_system_errors(**kwargs)
        except Exception as exc:
            kwargs["db"].rollback()
            return {"fixed_code": None, "report": f"### System repair ERROR\n{exc}"}

    async def _run_system_testing(self, project_id, design_json, final_code, id_version, db):
        root = project_path(project_id)
        cache = root / ".sdlc" / f"system_suite_{id_version}.json"
        execution = create_test_execution(db, None, None, id_version, "INTEGRATION")
        stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
        logs, passed = [], False
        try:
            if cache.exists():
                suite = json.loads(cache.read_text(encoding="utf-8"))
            else:
                plans = build_test_plans(root)
                if not plans:
                    raise ValueError("No supported Python, Node or static web source found for system testing")
                validation_error = ""
                for generation in range(2):
                    raw = await self.testing_agent.execute(
                        user_input=("Generate SYSTEM INTEGRATION tests for the actual services. "
                                    "Use each plan's exact target and runner. Python framework must match source (FastAPI/Flask/Django/etc). "
                                    "For Python use isolated test database fixtures: create schema, seed data, override the exact imported dependency, "
                                    "and enter TestClient/lifespan context; never connect production DB. "
                                    "For Node test actual exported modules/routes/components, with the specified runner. "
                                    "Static frontend tests must verify real HTML/JS/assets. "
                                    "Do not guess routes, accept 404/500 for required features, assert True, skip import/setup errors, or mock the feature under test. "
                                    "Include at least one successful core business flow and its error path. "
                                    "Return JSON files for all targets plus optional conftest.py at their test directories.\n"
                                    f"EXECUTION PLANS: {json.dumps(plans)}\nDESIGN: {design_json}\n"
                                    f"PREVIOUS GENERATION VALIDATION ERROR: {validation_error}"), context=source_context(project_id))
                    try:
                        clean = validate_generated_tests(raw, plans, strict=True)
                        break
                    except (ValueError, SyntaxError) as exc:
                        validation_error = str(exc)
                else:
                    raise ValueError(validation_error)
                suite = {"plans": plans, "payload": clean}
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(suite), encoding="utf-8")
            # Restore the same suite on every run, so code repairs cannot weaken its contract.
            ModuleRunner._export(project_id, suite["payload"])
            passed = True
            refreshed = {(p["runtime"], p["root"]): p for p in build_test_plans(root)}
            for cached_plan in suite["plans"]:
                plan = dict(cached_plan)
                current = refreshed.get((plan["runtime"], plan["root"]), {})
                for field in ("dependencies", "has_package", "has_build", "files", "environment"):
                    if field in current:
                        plan[field] = current[field]
                outcome = await run_test_plan(root, plan, strict=True, regression=True)
                passed = passed and outcome["status"] == "passed"
                for key in stats:
                    stats[key] += outcome["stats"][key]
                logs.append(f"[{plan['root']} / {plan['runner']}]\n{outcome['log']}")
        except Exception as exc:
            passed = False
            stats["errors"] += 1
            logs.append(f"{type(exc).__name__}: {exc}")
        log = "\n\n".join(logs)
        status = "PASSED" if passed else "FAILED"
        finish_test_execution(db, execution, status, stats["total"], stats["passed"],
                              stats["failed"] + stats["errors"], stats["skipped"], log)
        report = (f"### System + unit regression: {status}\n"
                  f"Total: {stats['total']} | Passed: {stats['passed']} | Failed: {stats['failed']} | "
                  f"Errors: {stats['errors']} | Skipped: {stats['skipped']}\n")
        if not passed:
            report += f"```text\n{log[-6000:]}\n```"
        return {"status": "passed" if passed else "failed", "report": report, "log": log}

    async def _fix_system_errors(self, project_id, final_code, error_log, db):
        root = project_path(project_id)
        test_context = []
        # Include exact frozen tests, not only application JSON prefixes.
        for cache in (root / ".sdlc").glob("system_suite_*.json"):
            test_context.append(json.loads(cache.read_text(encoding="utf-8"))["payload"])
        fixed = await self.dev_agent.execute(
            user_input=("Repair integration/regression failures. Use actual source/contracts and full traceback. "
                        "Fix dependency injection, schema setup, environment and business logic at the correct layer. "
                        "Do not edit test files, mock application behavior or swallow exceptions. "
                        "If the test contract is invalid, explain the exact cause in validation_issues; do not fake a passing result. "
                        "Return complete changed application/config files as JSON files.\n"
                        f"FAILURE LOG:\n{error_log[-20000:]}\nFROZEN SYSTEM TESTS:\n{''.join(test_context)}"),
            context=source_context(project_id))
        clean = self._apply_patch(project_id, fixed)
        return {"fixed_code": clean, "report": "### Integration repair applied; the same suite will be rerun."}

    @staticmethod
    def _apply_patch(project_id, payload):
        clean = merge_code_files('{"files": []}', _extract_pure_json(payload))
        files = json.loads(clean)["files"]
        if not files or any(is_test_path(f["file_path"]) for f in files):
            raise ValueError("Expected nonempty application/config patch without test files")
        ModuleRunner._export(project_id, clean)
        return clean

    @staticmethod
    def _available_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    async def _command(args, cwd, timeout=60):
        return await asyncio.to_thread(subprocess.run, args, cwd=str(cwd), capture_output=True,
                                       text=True, encoding="utf-8", errors="replace", timeout=timeout)

    async def _start_docker(self, project_id, app_port=None, design_obj=None):
        root = project_path(project_id)
        compose_file = next((root / n for n in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml") if (root / n).exists()), None)
        if compose_file is None:
            return {"status": "failed", "preview_url": None, "log": "Missing Compose configuration"}
        log = []
        base = None
        try:
            prefix = ["docker", "compose"]
            version = await self._command(prefix + ["version"], root)
            if version.returncode != 0:
                prefix = ["docker-compose"]
            original = prefix + ["--project-directory", str(root), "-f", str(compose_file)]
            config_result = await self._command(original + ["config", "--format", "json"], root)
            if config_result.returncode:
                raise ValueError(config_result.stderr)
            config = json.loads(config_result.stdout)
            services = config.get("services", {})
            if design_obj is None and (root / "design.json").exists():
                design_obj = json.loads((root / "design.json").read_text(encoding="utf-8"))
            execution = (design_obj or {}).get("execution", {})
            explicit = execution.get("preview_service")
            candidates = [name for name, spec in services.items() if spec.get("ports")]
            if explicit in services:
                selected = explicit
            else:
                preferred = ["frontend", "web", "client", "ui", "app", "backend", "api"]
                selected = next((name for name in preferred if name in candidates), candidates[0] if candidates else None)
            if selected is None:
                raise ValueError("No web service with published ports; specify execution.preview_service and its container_port")
            ports = services[selected].get("ports", [])
            target = execution.get("container_port") or (ports[0].get("target") if ports else None)
            if not target:
                raise ValueError("Preview service is missing container port")
            app_port = app_port or (int(ports[0]["published"]) if ports and ports[0].get("published") else self._available_port())
            for name, spec in services.items():
                spec.pop("container_name", None)
                if spec.get("build"):
                    spec.pop("image", None)
                spec.pop("ports", None)
            services[selected]["ports"] = [{"target": int(target), "published": str(app_port), "host_ip": "127.0.0.1", "protocol": "tcp"}]
            config.pop("name", None)
            normalized = root / ".sdlc" / "compose.preview.json"
            normalized.parent.mkdir(exist_ok=True)
            normalized.write_text(json.dumps(config), encoding="utf-8")
            base = prefix + ["--project-directory", str(root), "-p", "sdlc-" + re.sub(r"[^a-z0-9_-]", "", project_id.lower()), "-f", str(normalized)]
            result = await self._command(base + ["up", "-d", "--build", "--remove-orphans", "--wait", "--wait-timeout", "120"], root, timeout=600)
            log.append(result.stdout + "\n" + result.stderr)
            if result.returncode:
                raise ValueError("Compose build/start/health check failed")
            ps = await self._command(base + ["ps", "--all", "--format", "json"], root)
            if ps.returncode:
                raise ValueError(ps.stderr)
            rows = self._json_rows(ps.stdout)
            publishers = [pub for row in rows if row.get("Service") == selected for pub in row.get("Publishers") or [] if pub.get("TargetPort") == int(target)]
            if not publishers:
                raise ValueError("Preview service has no published port")
            actual_port = publishers[0]["PublishedPort"]
            url = f"http://localhost:{actual_port}" + execution.get("preview_path", "/")
            expect_html = any(Path(f["file_path"]).suffix == ".html" or Path(f["file_path"]).suffix in {".jsx", ".tsx", ".vue", ".svelte"} for f in source_snapshot(project_id)["files"])
            smoke = await self._wait_for_preview(url, expect_html=expect_html)
            if smoke is not True:
                raise ValueError(str(smoke))
            return {"status": "passed", "preview_url": url, "log": "\n".join(log), "service": selected}
        except Exception as exc:
            log.append(f"{type(exc).__name__}: {exc}")
            if base:
                for args in (["ps", "--all"], ["logs", "--no-color", "--tail", "100"]):
                    try:
                        diagnostic = await self._command(base + args, root)
                        log.append(diagnostic.stdout + "\n" + diagnostic.stderr)
                    except Exception as diagnostic_error:
                        log.append(str(diagnostic_error))
            return {"status": "failed", "preview_url": None, "log": "\n".join(log)}

    @staticmethod
    def _json_rows(value):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [json.loads(line) for line in value.splitlines() if line.strip()]

    async def _wait_for_preview(self, url, expect_html=True):
        def probe():
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    body = response.read(2_000_000).decode("utf-8", errors="replace")
                    content_type = response.headers.get("Content-Type", "")
                    if not 200 <= response.status < 300:
                        return f"Unexpected HTTP status {response.status}"
                    if expect_html and ("text/html" not in content_type or not re.search(r"<(?:html|body|!doctype)\b", body, re.I)):
                        return "Preview returns API/non-HTML content instead of the generated frontend"
                    class Assets(HTMLParser):
                        def __init__(self):
                            super().__init__(); self.urls = []
                        def handle_starttag(self, tag, attrs):
                            attrs = dict(attrs)
                            if tag == "script" and attrs.get("src"):
                                self.urls.append(attrs["src"])
                            if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
                                self.urls.append(attrs["href"])
                    assets = Assets(); assets.feed(body)
                    for asset in assets.urls:
                        asset_url = urljoin(response.url, asset)
                        if urlparse(asset_url).netloc != urlparse(response.url).netloc:
                            continue
                        with urllib.request.urlopen(asset_url, timeout=3) as item:
                            if not 200 <= item.status < 300:
                                return f"Broken frontend asset: {asset}"
                            if "text/html" in item.headers.get("Content-Type", ""):
                                return f"Frontend asset resolves to an HTML fallback: {asset}"
                    return True
            except Exception as exc:
                return f"Preview HTTP check failed: {exc}"
        deadline = time.monotonic() + 30
        error = "Preview did not respond"
        while time.monotonic() < deadline:
            error = await asyncio.to_thread(probe)
            if error is True:
                return True
            if "non-HTML" in str(error) or "Broken frontend asset" in str(error) or "HTML fallback" in str(error):
                break
            await asyncio.sleep(1)
        return error

    def _build_design_report(self, design_obj):
        modules = design_obj.get("architecture_modules", [])
        return "### Architecture\n" + "\n".join(f"- `{m.get('module_id', '?')}`: {m.get('description', '')}" for m in modules)

    def _error_result(self, srs_json, design_json, error_msg):
        return {"action": "PIPELINE_FAILED", "message": str(error_msg), "srs_data": srs_json,
                "design_data": design_json, "code_data": "{}", "failed_module": "design_phase", "id_version": None}
