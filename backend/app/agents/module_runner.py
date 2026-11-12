"""Develop/test/fix one module using the runtime of its actual source files."""
import asyncio
import ast
import json
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

from app.models.module import ModuleAttempt
from app.services.file_service import (
    SANDBOX_DIR, IGNORED_DIRS, export_code_to_sandbox, source_context, is_test_path,
)
from app.services.json_utils import _extract_pure_json, merge_code_files
from app.services.module_service import (
    create_attempt, finish_attempt, create_test_execution, finish_test_execution,
    save_source_files, set_module_status, read_test_report, is_test_report_passed,
)
from app.agents.dev_agent import DevAgent
from app.agents.testing_agent import TestingAgent


def build_test_plans(project_dir, code=None, key="system"):
    """Select per-service runtime; package.json in a frontend never overrides Python."""
    root = Path(project_dir)
    manifests = {"python": [], "node": []}
    paths = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in names:
            rel = (Path(directory) / name).relative_to(root).as_posix()
            if not is_test_path(rel):
                paths.append(rel)
            if name in {"requirements.txt", "pyproject.toml"}:
                manifests["python"].append(Path(rel).parent)
            if name == "package.json":
                manifests["node"].append(Path(rel).parent)
    if code is not None:
        paths = [f["file_path"] for f in json.loads(code).get("files", [])]
    groups = {}
    for name in paths:
        path = Path(name)
        suffix = path.suffix.lower()
        if is_test_path(name):
            continue
        if suffix == ".py":
            runtime = "python"
        elif suffix in {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".html"}:
            runtime = "node"
        else:
            continue
        candidates = [m for m in manifests[runtime] if path.is_relative_to(m)]
        service_root = max(candidates, key=lambda m: len(m.parts)) if candidates else (path.parent if suffix == ".html" else Path("."))
        # Plain browser JS alongside static HTML belongs to that frontend directory.
        if runtime == "node" and not candidates:
            for parent in (path.parent, *path.parents):
                if (root / parent / "index.html").exists():
                    service_root = parent
                    break
        group = groups.setdefault((runtime, service_root.as_posix()), [])
        group.append(name)
    plans = []
    safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", key)
    for (runtime, service_root), names in sorted(groups.items()):
        manifest_path = root / service_root / "package.json"
        package = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        runner = "pytest" if runtime == "python" else ("jest" if "jest" in deps else "vitest")
        if runtime == "node" and "node --test" in package.get("scripts", {}).get("test", ""):
            runner = "node"
        suffix = ".py" if runtime == "python" else (".test.cjs" if runner == "node" else ".test.ts" if any(Path(n).suffix in {".ts", ".tsx"} for n in names) else ".test.js")
        filename = f"test_{safe_key}{suffix}" if runtime == "python" else f"{safe_key}{suffix}"
        target = (Path(service_root) / "tests" / filename).as_posix()
        plans.append({"runtime": runtime, "root": service_root, "runner": runner, "target": target,
                      "files": names, "has_package": manifest_path.exists(),
                      "has_build": "build" in package.get("scripts", {}), "dependencies": sorted(deps),
                      "environment": "jsdom" if runtime == "node" and (
                          any(Path(n).suffix in {".html", ".jsx", ".tsx", ".vue", ".svelte"} for n in names)
                          or any(re.search(r"\b(?:document|window|localStorage|HTMLElement)\b", (root / n).read_text(encoding="utf-8", errors="replace"))
                                 for n in names if (root / n).is_file() and Path(n).suffix in {".js", ".ts", ".mjs"})
                      ) else "node"})
    return plans


def validate_local_python_imports(project_dir, code):
    """Mocked unit tests must not hide missing imports inside generated packages."""
    root = Path(project_dir)
    for item in json.loads(code)["files"]:
        path = Path(item["file_path"])
        if path.suffix != ".py":
            continue
        tree = ast.parse(item["code"], filename=item["file_path"])
        service_roots = [root]
        for parent in path.parents:
            absolute = root / parent
            if (absolute / "requirements.txt").exists() or (absolute / "pyproject.toml").exists():
                service_roots.insert(0, absolute)
        service_roots = sorted(set(service_roots), key=lambda p: len(p.parts), reverse=True)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
                if node.level:
                    base = (root / path).parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    target = base.joinpath(*(node.module or "").split("."))
                    if node.module and not target.is_dir() and not target.with_suffix(".py").is_file():
                        raise ValueError(f"Missing local import {node.module} in {path}")
                    continue
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                parts = name.split(".")
                for base in service_roots:
                    # Only inspect imports belonging to a real local package.
                    if len(parts) < 2 or not (base / parts[0]).is_dir():
                        continue
                    target = base.joinpath(*parts)
                    if not target.is_dir() and not target.with_suffix(".py").is_file():
                        raise ValueError(f"Missing local import {name} in {path}; implement the declared provider or use the existing interface")
                    break


def validate_generated_tests(payload, plans, strict=False):
    data = json.loads(merge_code_files('{"files": []}', _extract_pure_json(payload)))
    targets = {p["target"] for p in plans}
    allowed = targets | {(Path(p["target"]).parent / "conftest.py").as_posix() for p in plans if p["runtime"] == "python"}
    paths = {f["file_path"] for f in data["files"]}
    if not targets.issubset(paths) or not paths.issubset(allowed):
        raise ValueError(f"Test response must contain {sorted(targets)}; only test targets/conftest are allowed")
    for item in data["files"]:
        code = item["code"]
        if item["file_path"].endswith(".py"):
            tree = ast.parse(code)
            if strict:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"skip", "importorskip", "skipif", "xfail"}:
                        raise ValueError("System tests cannot skip import/setup failures or mark expected failures")
                    if isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant) and node.test.value is True:
                        raise ValueError("System tests cannot use assert True as a fallback")
        elif strict and re.search(r"\b(?:it|test|describe)\.(?:skip|todo|skipIf|fails)\s*\(", code):
            raise ValueError("System tests cannot skip required cases")
    return json.dumps(data, ensure_ascii=False)


def vitest_config(project_dir, plan):
    root = Path(project_dir) / plan["root"]
    config = next((name for prefix in ("vitest", "vite") for suffix in ("ts", "mts", "js", "mjs", "cjs", "cts")
                   if (root / (name := f"{prefix}.config.{suffix}")).is_file()), None)
    initial = (f"import original from {json.dumps('./' + config)};\n" if config else "const original = {};\n")
    # Preserve plugins/aliases/setup; replace discovery so generated targets cannot be excluded.
    return initial + """export default async (env) => {
      const base = await (typeof original === 'function' ? original(env) : original);
      const test = {...(base?.test || {})}; delete test.projects; delete test.workspace;
      return {...base, test: {...test, include: ['tests/**/*.test.{js,jsx,ts,tsx,mjs,cjs}', 'tests/**/*.spec.{js,jsx,ts,tsx,mjs,cjs}'],
        passWithNoTests: false, allowOnly: false}};
    };
"""


async def run_test_plan(project_dir, plan, *, strict=False, regression=False):
    """Install/run in an isolated copy; source mount is read-only, reports persist."""
    root = Path(project_dir).resolve()
    run_id = uuid.uuid4().hex
    report_dir = root / ".sdlc" / "reports" / run_id
    report_dir.mkdir(parents=True)
    report_name = "result.json" if plan["runner"] == "jest" else "result.xml"
    system_target = Path(plan["target"]).relative_to(plan["root"]).as_posix()
    target = "tests" if regression else system_target
    q = shlex.quote
    prefix = ("set -eu; mkdir -p /work; "
              "tar -C /source --exclude=node_modules --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.sdlc -cf - . | tar -C /work -xf -; "
              f"cd {q('/work/' + plan['root'])}; ")
    if plan["runtime"] == "python":
        install = ("if [ -f requirements.txt ]; then pip install -r requirements.txt -q; "
                   "elif [ -f pyproject.toml ]; then pip install . -q; fi; "
                   "pip install pytest pytest-mock httpx -q; ")
        command = f"PYTHONPATH=$PWD:/work pytest {q(target)} -v --tb=short -rs --junitxml=/reports/{report_name}"
        image = "python:3.11-slim"
    else:
        install = "npm install --no-audit --no-fund; " if plan["has_package"] else ""
        if plan["runner"] == "vitest":
            # Pin the fallback only; declared framework/test versions remain project-owned.
            extras = ["vitest@3"] if "vitest" not in plan["dependencies"] else []
            if "jsdom" not in plan["dependencies"]:
                extras.append("jsdom@26")
            if extras:
                install += "npm install --no-save --package-lock=false --no-audit --no-fund " + " ".join(extras) + "; "
            env = plan.get("environment", "node")
            install += "printf %s " + q(vitest_config(root, plan)) + " > .sdlc.vitest.config.mjs; "
            command = f"./node_modules/.bin/vitest run {q(target)} --config=.sdlc.vitest.config.mjs --environment={env} --maxWorkers=1 --minWorkers=1 --reporter=default --reporter=junit --outputFile=/reports/{report_name}"
        elif plan["runner"] == "jest":
            command = f"./node_modules/.bin/jest --runInBand --runTestsByPath {q(target)} --json --outputFile=/reports/{report_name}"
            if regression:
                command = f"./node_modules/.bin/jest {q(target)} --runInBand --json --outputFile=/reports/{report_name}"
        else:
            command = f"node --test --test-reporter=junit --test-reporter-destination=/reports/{report_name} {q(target)}"
        if strict and plan["has_build"]:
            install += "npm run build; "
        image = "node:22-bookworm-slim"
    # Run system checks in a fresh process before broad unit-test collection can
    # install module-level mocks that hide application import failures.
    system_report_name = "system." + ("json" if plan["runner"] == "jest" else "xml")
    if strict and regression:
        if plan["runner"] == "pytest":
            system_command = f"PYTHONPATH=$PWD:/work pytest {q(system_target)} -v --tb=short -rs --junitxml=/reports/{system_report_name}"
        elif plan["runner"] == "jest":
            system_command = f"./node_modules/.bin/jest --runInBand --runTestsByPath {q(system_target)} --json --outputFile=/reports/{system_report_name}"
        elif plan["runner"] == "vitest":
            system_command = f"./node_modules/.bin/vitest run {q(system_target)} --config=.sdlc.vitest.config.mjs --environment={env} --maxWorkers=1 --minWorkers=1 --reporter=default --reporter=junit --outputFile=/reports/{system_report_name}"
        else:
            system_command = f"node --test --test-reporter=junit --test-reporter-destination=/reports/{system_report_name} {q(system_target)}"
        command = system_command + " && " + command
    container_name = "sdlc-test-" + run_id
    cmd = ["docker", "run", "--rm", "--name", container_name,
           "-v", f"{root}:/source:ro", "-v", f"{report_dir}:/reports", "-w", "/work",
           "-e", "CI=true", "-e", "SDLC_TESTING=1", "-e", "DATABASE_URL=sqlite:////tmp/sdlc-test.db",
           image, "sh", "-c", prefix + install + command]
    stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    try:
        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=600)
        log = result.stdout + "\n" + result.stderr
        rc = result.returncode
        try:
            available_report = report_dir / report_name
            if not available_report.exists() and strict and regression:
                available_report = report_dir / system_report_name
            stats = read_test_report(available_report)
            if strict and regression:
                system_stats = read_test_report(report_dir / system_report_name)
                if not is_test_report_passed(0, system_stats, True):
                    rc = rc or 1
                    log += "\nIsolated system suite did not pass its quality gate."
        except Exception as exc:
            rc = rc or 1
            log += f"\nNo valid structured test report: {exc}"
        passed = is_test_report_passed(rc, stats, strict)
        if not passed and rc == 0:
            log += "\nQuality gate failed: no passing tests, skipped system checks, or test errors."
    except subprocess.TimeoutExpired as exc:
        rc, passed = 124, False
        log = "Test environment timed out after 600 seconds."
        for output in (exc.stdout, exc.stderr):
            if output:
                log += "\n" + (output.decode(errors="replace") if isinstance(output, bytes) else output)
    except OSError as exc:
        rc, passed, log = 127, False, str(exc)
    finally:
        # Only this invocation's uniquely named test container; never remove project volumes.
        try:
            await asyncio.to_thread(subprocess.run, ["docker", "rm", "-f", container_name], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            pass
    (report_dir / "output.log").write_text(log, encoding="utf-8")
    return {"status": "passed" if passed else "failed", "log": log, "stats": stats,
            "return_code": rc, "report_path": str(report_dir / report_name)}


class ModuleRunner:
    def __init__(self):
        self.dev_agent = DevAgent()
        self.testing_agent = TestingAgent()

    async def run(self, project_id, module, design_json, completed_interfaces, id_version, db):
        current_code = '{"files": []}'
        clean_test = None
        plans = []
        report = ""
        used = 0
        max_attempts = max(1, module.max_retries if module.max_retries is not None else 3)
        start_number = (module.retry_count or 0) + 1
        source_invalid = False
        for index in range(max_attempts):
            used += 1
            module.retry_count = start_number + index
            db.commit()
            attempt = create_attempt(db, module.id_module, start_number + index, "CODING" if index == 0 else "FIXING")
            try:
                set_module_status(db, module, "CODING")
                if current_code == '{"files": []}' or clean_test is not None or source_invalid:
                    if current_code == '{"files": []}':
                        raw = await self._dev_code(module, design_json, completed_interfaces + "\nPREVIOUS GENERATION ERROR: " + report, current_code)
                    else:
                        raw = await self._fix_code(module, current_code, clean_test, report, source_context(project_id))
                    patch_data = json.loads(merge_code_files('{"files": []}', _extract_pure_json(raw)))
                    if not patch_data["files"]:
                        raise ValueError("Developer returned no files")
                    if any(is_test_path(f["file_path"]) for f in patch_data["files"]):
                        if clean_test is not None:
                            raise ValueError("Developer cannot overwrite tests")
                        # Legacy designs sometimes list test files in Dev specs. Ignore Dev tests;
                        # QA must independently generate the authoritative test contract.
                        patch_data["files"] = [f for f in patch_data["files"] if not is_test_path(f["file_path"])]
                        if not patch_data["files"]:
                            raise ValueError("Developer returned tests without application source")
                    current_code = merge_code_files(current_code, json.dumps(patch_data))
                    self._export(project_id, current_code)
                    source_invalid = True
                    validate_local_python_imports(SANDBOX_DIR / project_id, current_code)
                    source_invalid = False
                attempt.source_revision = current_code
                module.retry_count = start_number + index
                db.commit()
                if not module.is_testable:
                    finish_attempt(db, attempt, "SUCCESS", source_revision=current_code)
                    if id_version:
                        save_source_files(db, id_version, module.id_module, current_code)
                    set_module_status(db, module, "PASSED")
                    return {"status": "skipped", "final_code": current_code,
                            "test_report": f"### `{module.module_key}`: generated; unit test not applicable", "attempts": used}
                if clean_test is None:
                    plans = build_test_plans(SANDBOX_DIR / project_id, current_code, module.module_key)
                    if not plans:
                        raise ValueError("No supported runtime found for this testable module")
                    raw_test = await self._gen_tests(module, current_code, source_context(project_id) + "\nTEST GENERATION VALIDATION: " + report, plans)
                    clean_test = validate_generated_tests(raw_test, plans)
                    self._export(project_id, clean_test)
                set_module_status(db, module, "TESTING")
                results = []
                for plan in plans:
                    execution = create_test_execution(db, module.id_module, attempt.id_attempt, id_version, "UNIT")
                    try:
                        outcome = await run_test_plan(SANDBOX_DIR / project_id, plan)
                    except Exception as exc:
                        outcome = {"status": "failed", "log": f"Test infrastructure error: {exc}",
                                   "stats": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 1}}
                    stats = outcome["stats"]
                    finish_test_execution(db, execution, "PASSED" if outcome["status"] == "passed" else "FAILED",
                                          stats["total"], stats["passed"], stats["failed"] + stats["errors"], stats["skipped"], outcome["log"])
                    results.append(outcome)
                report = "\n\n".join(f"### `{module.module_key}` / {p['runner']} / {r['status'].upper()}\n{r['log'][-10000:]}"
                                        for p, r in zip(plans, results))
                if all(result["status"] == "passed" for result in results):
                    finish_attempt(db, attempt, "SUCCESS", source_revision=current_code)
                    if id_version:
                        save_source_files(db, id_version, module.id_module, current_code)
                    set_module_status(db, module, "PASSED")
                    return {"status": "passed", "final_code": current_code, "test_report": report, "attempts": used}
                finish_attempt(db, attempt, "FAILED", error_summary=report, source_revision=current_code)
            except Exception as exc:
                db.rollback()
                report = f"### `{module.module_key}` / FAILED\n{type(exc).__name__}: {exc}"
                finish_attempt(db, attempt, "FAILED", error_summary=report, source_revision=current_code)
                # Invalid/missing generated tests must be regenerated, not treated as app bugs.
                if clean_test is None:
                    continue
        if id_version and json.loads(current_code)["files"]:
            save_source_files(db, id_version, module.id_module, current_code)
        set_module_status(db, module, "FAILED")
        return {"status": "failed", "final_code": current_code, "test_report": report, "attempts": used}

    async def _dev_code(self, module, design_json, completed_interfaces, prev_code):
        return await self.dev_agent.execute(
            user_input=f"Implement ALL files of module {module.module_key}. SPEC: {module.specification}\n"
                       "Preserve existing dependency interfaces. Merge dependencies into existing manifests; do not remove libraries. "
                       "Do not invent methods or endpoints. Return complete changed application files only, as JSON {files:[{file_path,code}]}.\n"
                       f"ACTUAL EXISTING SOURCE:\n{completed_interfaces}", context=design_json)

    async def _gen_tests(self, module, module_code, completed_interfaces="", plans=None):
        return await self.testing_agent.execute(
            user_input=f"Generate UNIT tests for {module.module_key}. SPEC: {module.specification}\n"
                       f"EXECUTION PLANS (use exact target files and specified runners): {json.dumps(plans)}\n"
                       "Mock outside dependencies using their ACTUAL signatures and required schema fields. "
                       "Do not guess interfaces or test unrelated features. Return JSON files plus optional test_cases.\n"
                       f"MODULE SOURCE:\n{module_code}", context=completed_interfaces)

    async def _fix_code(self, module, current_code, test_code, error_log, existing_context=""):
        return await self.dev_agent.execute(
            user_input=f"Repair module {module.module_key} using specification {module.specification}.\n"
                       "Classify the actual cause (dependency, interface, configuration, logic). "
                       "Preserve existing public interfaces and all dependencies. You may repair a shared dependency if its contract is broken. "
                       "Do not change tests, suppress errors, or replace real functionality with mocks. "
                       "Return only complete changed application/config files as JSON files.\n"
                       f"CURRENT MODULE:\n{current_code}\nFIXED TEST CONTRACT:\n{test_code}\nFAILURE LOG:\n{error_log[-18000:]}",
            context=existing_context)

    @staticmethod
    def _export(project_id, payload):
        success, details = export_code_to_sandbox(project_id, payload)
        if not success or not details:
            raise ValueError(f"Could not export generated files: {details}")
