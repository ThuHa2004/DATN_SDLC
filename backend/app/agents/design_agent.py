from app.agents.base_agent import BaseAgent


class DesignAgent(BaseAgent):
    def __init__(self):
        role = """
You design the architecture of a website from its SRS. Choose the appropriate stack; do not force all websites into FastAPI.
Return valid JSON with project_name, tech_stack, execution, architecture_modules.
execution: {"preview_service":"web service name in compose", "preview_path":"/", "container_port":3000, "services":[{"name":"service name", "root":". or backend/frontend", "runtime":"python|node|static", "framework":"actual framework", "test_runner":"pytest|vitest|jest|node", "entrypoint":"actual entrypoint", "build_command":"actual build command if any", "start_command":"actual start command"}]}.
architecture_modules is a DAG of {"module_id":"unique_safe_identifier", "layer":"Core|Data|Logic|API|Frontend", "dependencies":["existing module ids"], "is_testable":true, "description":"...", "files":[{"file_path":"relative source path", "purpose":"...", "exported_interfaces":["exact signature/contracts"]}]}.
Every module must have dependencies and is_testable. Dependencies must exist, contain no cycles, and include actual providers. Configuration comes first; entrypoints integrating routers and the UI come after their dependencies.
Define common request/response schemas, DB Base, canonical dependency providers, route paths and exported signatures once so downstream agents reuse them.
Do NOT put test files or conftest.py in architecture_modules.files: tests are owned exclusively by TestingAgent and the runner chooses their paths. Vitest config must include tests/**/*.test.* rather than only src tests.
Each service must have a complete appropriate requirements.txt/package.json and runtime/test/build dependencies. Mark config/migrations/static HTML/CSS as not unit-testable; mark executable business logic/components as testable.
Include application bootstrap, database initialization/migrations and frontend integration so the result is runnable. Preview must show the actual website, not just a JSON API. Keep services/ports/entrypoints in execution consistent with module files. Return JSON only.
"""
        super().__init__(name='Design Agent', role_description=role, model_name="deepseek-chat")
