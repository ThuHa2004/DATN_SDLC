"""Opt-in paid-provider E2E; isolated in-memory DB, separate retained sandbox."""
import asyncio
import json
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Base, User, Project, Module, TestExecution
from app.agents.pipeline_runner import PipelineRunner
from app.services.file_service import project_path


async def main():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id="sdlc-e2e-"+uuid.uuid4().hex[:12]
    print("ISOLATED E2E PROJECT:",project_id,flush=True)
    with Session(engine) as db:
        user=User(user_name="Runtime verification",email=project_id+"@example.invalid",password_hash="verification-only")
        db.add(user);db.flush()
        db.add(Project(id_project=project_id,id_user=user.id_user,project_name="Static calculator verification",project_status="GATHERING"));db.commit()
        runner=PipelineRunner()
        requirements=("Build a small static tip calculator website. Plain HTML/CSS/JavaScript ES modules only, no backend, DB or login. "
            "Enter bill amount and tip percentage, click Calculate and display tip and total to two decimals. "
            "Reject negative values, blank and non-numeric input with a visible error. Simple responsive English UI. "
            "Use package.json with Vitest; put all generated tests only in tests/, never in Dev module files. "
            "Use nginx static preview at /. Limit the design to 3 source modules: scaffold/HTML/CSS, calculation logic, UI wiring. "
            "All requirements are final; implement, test and preview.")
        result=await runner.run_full_pipeline(project_id,requirements,"[READY] Requirements complete.",db)
        summary={key:result.get(key) for key in ("action","preview_url","quality_passed","system_test_passed","failed_modules")}
        summary["project_id"]=project_id
        summary["modules"]=[{"key":m.module_key,"status":m.status,"attempts":m.retry_count} for m in db.query(Module).all()]
        summary["executions"]=[{"type":e.test_type,"status":e.status,"passed":e.passed_tests,"failed":e.failed_tests,"skipped":e.skipped_tests} for e in db.query(TestExecution).all()]
        folder=project_path(project_id)/".sdlc";folder.mkdir(parents=True,exist_ok=True)
        (folder/"e2e-result.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        (folder/"e2e-message.md").write_text(result.get("message",""),encoding="utf-8")
        print("E2E RESULT:",json.dumps(summary),flush=True)
        if not summary["quality_passed"] or not summary["preview_url"]:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
