import asyncio
import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from app.agents.module_runner import ModuleRunner, build_test_plans, validate_generated_tests, run_test_plan, validate_local_python_imports
from app.agents.pipeline_runner import PipelineRunner
from app.agents.orchestrator import Orchestrator
from app.services.file_service import export_code_to_sandbox, source_context, source_snapshot
from app.services.json_utils import merge_code_files, extract_pure_json
from app.services.module_service import read_test_report, is_test_report_passed, parse_pytest_output, _topological_sort


def payload(name, code="source"):
    return json.dumps({"files": [{"file_path": name, "code": code}]})


def outcome(status="passed"):
    return {"status": status, "log": "trace", "stats": {"total": 1, "passed": int(status == "passed"),
            "failed": int(status != "passed"), "errors": 0, "skipped": 0}, "return_code": int(status != "passed")}


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sandbox = Path(self.temp.name)
        self.root = self.sandbox / "project"
        self.root.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("app.services.file_service.SANDBOX_DIR", "app.agents.module_runner.SANDBOX_DIR", "app.agents.pipeline_runner.SANDBOX_DIR"):
            self.stack.enter_context(patch(target, self.sandbox))

    def write(self, name, code=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        return path

    def test_mixed_website_uses_separate_service_runtimes(self):
        self.write("backend/requirements.txt", "flask")
        self.write("backend/app.py", "x=1")
        self.write("frontend/package.json", '{"dependencies":{"react":"18"},"scripts":{"build":"vite build"}}')
        self.write("frontend/src/App.tsx", "export default function App() {}")
        plans = build_test_plans(self.root)
        self.assertEqual({(p["root"], p["runner"]) for p in plans}, {("backend", "pytest"), ("frontend", "vitest")})

    def test_root_package_does_not_turn_python_into_node(self):
        self.write("package.json", "{}")
        self.write("requirements.txt")
        self.write("app/main.py", "x=1")
        self.assertEqual(build_test_plans(self.root, payload("app/main.py", "x=1"))[0]["runner"], "pytest")

    def test_static_frontend_has_its_own_test_root(self):
        self.write("frontend/index.html", "<html></html>")
        self.write("frontend/js/main.js", "const a=1")
        plans = build_test_plans(self.root)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["root"], "frontend")

    def test_declared_jest_runner_is_preserved(self):
        self.write("package.json", '{"devDependencies":{"jest":"29"}}')
        self.write("app.js", "module.exports={}")
        self.assertEqual(build_test_plans(self.root)[0]["runner"], "jest")

    def test_valid_source_json_is_never_rewritten(self):
        code = 'const a = ", }"; const b = ", ]";\n'
        data = json.loads(extract_pure_json(payload("a.js", code)))
        self.assertEqual(data["files"][0]["code"], code)

    def test_truncated_json_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_pure_json('{"files":[{"file_path":"a.py","code":"oops')

    def test_trailing_comma_repair_preserves_code(self):
        raw = '{"files":[{"file_path":"a.js","code":"const x = ", }";"},],}'
        # The JSON emitted below has one trailing comma, but its code contains comma+brace.
        raw = payload("a.js", 'const x = ", }";')[:-1] + ",}"
        self.assertEqual(json.loads(extract_pure_json(raw))["files"][0]["code"], 'const x = ", }";')

    def test_dotfiles_preserved_and_traversal_rejected_before_writes(self):
        ok, _ = export_code_to_sandbox("project", payload(".env.example", "DEMO=1"))
        self.assertTrue(ok)
        self.assertTrue((self.root / ".env.example").exists())
        bad = json.dumps({"files":[{"file_path":"safe.py","code":"x"},{"file_path":"../escape.py","code":"x"}]})
        self.assertFalse(export_code_to_sandbox("project", bad)[0])
        self.assertFalse((self.root / "safe.py").exists())

    def test_context_contains_complete_dependency_beyond_old_2000_limit(self):
        self.write("app/service.py", "#" * 6000 + "\ndef required_method(): return 1\n")
        self.write(".env", "HIDDEN=value")
        self.assertIn("def required_method", source_context("project"))
        self.assertNotIn("HIDDEN=value", source_context("project"))

    def test_partial_patch_keeps_other_files(self):
        initial = merge_code_files(payload("a.py"), payload("b.py"))
        merged = json.loads(merge_code_files(initial, payload("a.py", "fixed")))
        self.assertEqual({f["file_path"]:f["code"] for f in merged["files"]}, {"a.py":"fixed", "b.py":"source"})

    def test_collection_errors_are_counted(self):
        path = self.write("report.xml", '<testsuites><testsuite errors="1"><testcase name="collection"><error>bad import</error></testcase></testsuite></testsuites>')
        stats = read_test_report(path)
        self.assertEqual(stats["errors"], 1)
        self.assertFalse(is_test_report_passed(0, stats))

    def test_three_passed_fifteen_skipped_is_not_system_success(self):
        xml = '<testsuites><testsuite>' + '<testcase name="ok"/>' * 3 + '<testcase name="skip"><skipped/></testcase>' * 15 + '</testsuite></testsuites>'
        stats = read_test_report(self.write("report.xml", xml))
        self.assertEqual(stats["passed"], 3)
        self.assertEqual(stats["skipped"], 15)
        self.assertFalse(is_test_report_passed(0, stats, strict=True))

    def test_zero_tests_cannot_pass(self):
        stats = {"passed":0,"failed":0,"skipped":0,"errors":0,"total":0}
        self.assertFalse(is_test_report_passed(0,stats,True))

    def test_pytest_fallback_includes_setup_errors_and_latest_summary(self):
        stats = parse_pytest_output("2 passed\n1 passed, 2 failed, 3 errors, 4 skipped")
        self.assertEqual(stats, {"passed":1,"failed":2,"errors":3,"skipped":4,"total":10})

    def test_system_generator_cannot_write_application_or_skip_imports(self):
        plans=[{"target":"tests/test_system.py","runtime":"python"}]
        for data in (payload("app/main.py", "x=1"), payload("tests/test_system.py", "import pytest\ndef test_app(): pytest.skip('bad import')")):
            with self.assertRaises(ValueError):
                validate_generated_tests(data, plans, strict=True)

    def test_unit_mocks_cannot_hide_missing_local_repository(self):
        self.write("app/services/profile.py", "from app.repositories.profile import Repository")
        with self.assertRaisesRegex(ValueError, "Missing local import"):
            validate_local_python_imports(self.root, payload("app/services/profile.py", "from app.repositories.profile import Repository"))
        self.write("app/repositories/profile.py", "class Repository: pass")
        validate_local_python_imports(self.root, payload("app/services/profile.py", "from app.repositories.profile import Repository"))

    def test_manifest_patch_keeps_other_module_dependencies(self):
        self.write("requirements.txt", "fastapi==1.0\nhttpx\n")
        self.assertTrue(export_code_to_sandbox("project", payload("requirements.txt", "psycopg2-binary\nfastapi==2.0"))[0])
        text=(self.root / "requirements.txt").read_text()
        self.assertIn("httpx",text)
        self.assertIn("fastapi==2.0",text)
        self.assertNotIn("fastapi==1.0",text)
        self.write("package.json", '{"dependencies":{"react":"18"},"scripts":{"build":"vite build"}}')
        export_code_to_sandbox("project",payload("package.json",'{"devDependencies":{"vitest":"3"},"scripts":{"test":"vitest"}}'))
        data=json.loads((self.root / "package.json").read_text())
        self.assertEqual(data["dependencies"]["react"],"18")
        self.assertEqual(data["scripts"]["build"],"vite build")

    def test_dag_rejects_missing_dependencies_and_cycles(self):
        for modules in ([{"module_id":"a","dependencies":["missing"]}],
                        [{"module_id":"a","dependencies":["b"]},{"module_id":"b","dependencies":["a"]}]):
            with self.assertRaises(ValueError):
                _topological_sort(modules)

    async def test_test_container_source_is_readonly_and_no_report_cannot_pass(self):
        self.write("app.py", "x=1")
        plan=build_test_plans(self.root)[0]
        with patch("app.agents.module_runner.subprocess.run", return_value=subprocess.CompletedProcess([],0,"99 passed","")) as run:
            result=await run_test_plan(self.root, plan)
        self.assertEqual(result["status"],"failed")
        command=run.call_args_list[0].args[0]
        self.assertIn(str(self.root.resolve())+":/source:ro", command)
        self.assertFalse((self.root / "node_modules").exists())

    def test_root_browser_script_selects_dom_environment(self):
        self.write("package.json", "{}")
        self.write("ui.js", "document.querySelector('button').addEventListener('click', () => {});")
        self.assertEqual(build_test_plans(self.root,payload("ui.js",""))[0]["environment"],"jsdom")
        self.write("logic.js", "export const add=(a,b)=>a+b")
        self.assertEqual(build_test_plans(self.root,payload("logic.js",""))[0]["environment"],"node")

    async def test_empty_system_report_keeps_actual_process_diagnostics(self):
        self.write("app.py","x=1")
        plan=build_test_plans(self.root)[0]
        def execute(command, **kwargs):
            if command[:2]==["docker","run"]:
                report_mount=next(v for v in command if isinstance(v,str) and v.endswith(":/reports"))
                report_dir=Path(report_mount[:-len(":/reports")])
                (report_dir/"system.xml").write_text("")
                return subprocess.CompletedProcess(command,1,"real worker startup failure","")
            return subprocess.CompletedProcess(command,0,"","")
        with patch("app.agents.module_runner.subprocess.run",side_effect=execute):
            result=await run_test_plan(self.root,plan,strict=True,regression=True)
        self.assertEqual(result["status"],"failed")
        self.assertIn("real worker startup failure",result["log"])
        self.assertTrue(any(self.root.glob(".sdlc/reports/*/output.log")))

    async def test_module_retry_merges_patch_and_keeps_same_tests(self):
        runner=ModuleRunner.__new__(ModuleRunner)
        runner._dev_code=AsyncMock(return_value=merge_code_files(merge_code_files(payload("a.py","x=1"),payload("b.py","y=2")),payload("tests/test_legacy.py","def test_fake(): assert True")))
        runner._gen_tests=AsyncMock(return_value=payload("tests/test_demo.py","def test_x(): assert True"))
        runner._fix_code=AsyncMock(return_value=payload("a.py","x=2"))
        module=NS(id_module=1,module_key="demo",max_retries=2,retry_count=0,is_testable=True,specification="{}")
        with ExitStack() as stack:
            for name in ("finish_attempt","create_test_execution","finish_test_execution","save_source_files"):
                stack.enter_context(patch("app.agents.module_runner."+name))
            stack.enter_context(patch("app.agents.module_runner.create_attempt",side_effect=[NS(id_attempt=1),NS(id_attempt=2)]))
            stack.enter_context(patch("app.agents.module_runner.set_module_status",side_effect=lambda db,m,s:setattr(m,"status",s)))
            execute=stack.enter_context(patch("app.agents.module_runner.run_test_plan",side_effect=[outcome("failed"),outcome()]))
            result=await runner.run("project",module,"{}","",1,Mock())
        self.assertEqual(result["status"],"passed")
        self.assertEqual(execute.await_count,2)
        runner._gen_tests.assert_awaited_once()
        self.assertEqual(len(json.loads(result["final_code"])["files"]),2)
        self.assertEqual(module.status,"PASSED")
        self.assertFalse((self.root / "tests/test_legacy.py").exists())

    async def test_generation_errors_exhaust_only_module_retry_budget(self):
        runner=ModuleRunner.__new__(ModuleRunner)
        runner._dev_code=AsyncMock(side_effect=RuntimeError("provider failure"))
        module=NS(id_module=1,module_key="demo",max_retries=2,retry_count=0,is_testable=True,specification="{}")
        with patch("app.agents.module_runner.create_attempt",return_value=NS(id_attempt=1)), patch("app.agents.module_runner.finish_attempt"), patch("app.agents.module_runner.set_module_status"):
            result=await runner.run("project",module,"{}","",1,Mock())
        self.assertEqual(result["status"],"failed")
        self.assertEqual(runner._dev_code.await_count,2)

    async def test_system_suite_is_not_regenerated_on_second_attempt(self):
        self.write("app.py","x=1")
        runner=PipelineRunner.__new__(PipelineRunner)
        runner.testing_agent=NS(execute=AsyncMock(return_value=payload("tests/test_system.py","def test_app(): assert 1 == 1")))
        with patch("app.agents.pipeline_runner.create_test_execution"), patch("app.agents.pipeline_runner.finish_test_execution"), patch("app.agents.pipeline_runner.run_test_plan",side_effect=[outcome("failed"),outcome()]) as run:
            first=await runner._run_system_testing("project","{}","{}",1,Mock())
            second=await runner._run_system_testing("project","{}","{}",1,Mock())
        self.assertEqual(first["status"],"failed")
        self.assertEqual(second["status"],"passed")
        runner.testing_agent.execute.assert_awaited_once()
        self.assertTrue(all(c.kwargs["regression"] for c in run.call_args_list))

    async def exercise_pipeline(self, ready):
        runner=PipelineRunner.__new__(PipelineRunner)
        runner.srs_agent=NS(execute=AsyncMock(return_value="{}"))
        runner.design_agent=NS(execute=AsyncMock(return_value='{"architecture_modules":[]}'))
        runner.devops_agent=NS(execute=AsyncMock(return_value=payload("docker-compose.yml","services: {}")))
        runner.dev_agent=NS(execute=AsyncMock(return_value=payload("requirements.txt","flask")))
        modules=[NS(module_key=k,module_order=i,module_type="API",status="PENDING",specification="{}") for i,k in enumerate(("a","b"))]
        async def develop(**kwargs):
            m=kwargs["module"]
            m.status="FAILED" if m.module_key=="a" else "PASSED"
            export_code_to_sandbox("project",payload(m.module_key+".py","x=1"))
            return {"status":m.status.lower(),"test_report":"report","final_code":payload(m.module_key+".py","x=1")}
        runner.module_runner=NS(run=AsyncMock(side_effect=develop))
        runner._safe_system_testing=AsyncMock(return_value={"status":"failed","report":"failed","log":"cause"})
        runner._safe_fix_system_errors=AsyncMock(return_value={"fixed_code":None,"report":"unresolved"})
        runner._start_docker=AsyncMock(return_value={"status":"passed" if ready else "failed","preview_url":"http://localhost:9000" if ready else None,"log":"startup cause"})
        project=NS(project_status="INIT")
        db=Mock(); db.query.return_value.filter_by.return_value.first.return_value=project
        with patch("app.agents.pipeline_runner.create_modules_from_design",return_value=modules), patch("app.agents.pipeline_runner.save_source_files"):
            result=await runner.run_full_pipeline("project","history","ready",db)
        self.assertEqual(runner.module_runner.run.await_count,2)
        self.assertEqual(runner._safe_fix_system_errors.await_count,2)
        self.assertFalse(result["quality_passed"])
        return result,project,runner

    async def test_failed_module_still_reaches_real_preview_step(self):
        result,project,runner=await self.exercise_pipeline(True)
        self.assertEqual(project.project_status,"PREVIEW")
        self.assertEqual(result["failed_modules"],["a"])
        self.assertEqual(result["preview_url"],"http://localhost:9000")
        runner._start_docker.assert_awaited_once()

    async def test_failed_preview_is_retried_and_never_reported_ready(self):
        result,project,runner=await self.exercise_pipeline(False)
        self.assertEqual(runner._start_docker.await_count,3)
        self.assertEqual(project.project_status,"CODING_FAILED")
        self.assertIsNone(result["preview_url"])
        self.assertEqual(result["action"],"PIPELINE_FAILED")

    def test_compose_ps_accepts_json_array_and_json_lines(self):
        rows=[{"Service":"frontend"},{"Service":"db"}]
        self.assertEqual(PipelineRunner._json_rows(json.dumps(rows)),rows)
        self.assertEqual(PipelineRunner._json_rows("\n".join(json.dumps(r) for r in rows)),rows)

    async def test_preview_rejects_backend_json_when_frontend_expected(self):
        response=Mock(); response.status=200; response.headers={"Content-Type":"application/json"}; response.read.return_value=b'{"app":"API"}'
        response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
        with patch("app.agents.pipeline_runner.urllib.request.urlopen",return_value=response):
            result=await PipelineRunner.__new__(PipelineRunner)._wait_for_preview("http://localhost:9000",True)
        self.assertIn("non-HTML",result)

    def test_import_validation_uses_nearest_service_root(self):
        self.write("requirements.txt")
        self.write("app/unrelated.py", "x=1")
        self.write("backend/requirements.txt")
        self.write("backend/app/provider.py", "x=1")
        self.write("backend/app/main.py", "from app.provider import x")
        validate_local_python_imports(self.root,payload("backend/app/main.py","from app.provider import x"))

    async def exercise_feedback(self, ready):
        self.write("app.py","x=1")
        runner=PipelineRunner.__new__(PipelineRunner)
        runner._available_port=Mock(return_value=9000)
        runner._safe_system_testing=AsyncMock(return_value={"status":"passed","report":"passed","log":""})
        runner._safe_fix_system_errors=AsyncMock()
        failure={"status":"failed","preview_url":None,"log":"missing dependency"}
        success={"status":"passed","preview_url":"http://localhost:9000/","log":"ready"}
        runner._start_docker=AsyncMock(side_effect=[failure,success] if ready else [failure,failure,failure])
        orchestrator=Orchestrator.__new__(Orchestrator)
        orchestrator.pipeline_runner=runner
        orchestrator.dev_agent=NS(execute=AsyncMock(return_value=payload("app.py","x=2")))
        orchestrator.devops_agent=orchestrator.dev_agent
        with patch("app.agents.orchestrator.get_project_version",return_value=None):
            result=await orchestrator.handle_user_message("project","CODING_FAILED","Repair missing import",db=Mock())
        return result,runner

    async def test_feedback_repairs_preview_and_retests_changed_source(self):
        result,runner=await self.exercise_feedback(True)
        self.assertEqual(result["action"],"FINISH_FEEDBACK_AUTO")
        self.assertEqual(runner._start_docker.await_count,2)
        self.assertEqual(runner._safe_system_testing.await_count,2)

    async def test_feedback_exhaustion_does_not_claim_preview_success(self):
        result,runner=await self.exercise_feedback(False)
        self.assertEqual(result["action"],"PIPELINE_FAILED")
        self.assertEqual(runner._start_docker.await_count,3)
        self.assertIsNone(result["preview_url"])

    async def test_preview_api_propagates_verified_failure(self):
        import main
        project=NS(project_status="PREVIEW")
        db=Mock(); db.query.return_value.filter.return_value.first.return_value=project
        with patch.object(main.orchestrator.pipeline_runner,"_start_docker",AsyncMock(return_value={"status":"failed","preview_url":None,"log":"health failed"})):
            result=await main.run_docker_preview("project",db=db,current_user=NS(id_user=1))
        self.assertEqual(result["status"],"error")
        self.assertEqual(project.project_status,"CODING_FAILED")
        self.assertIsNone(result["preview_url"])

    async def test_missing_compose_returns_structured_failure(self):
        result=await PipelineRunner.__new__(PipelineRunner)._start_docker("project")
        self.assertEqual(result["status"],"failed")
        self.assertIsNone(result["preview_url"])


if __name__ == "__main__":
    unittest.main()
