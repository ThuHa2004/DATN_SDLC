from app.core.database import Base
from .user import User
from .project import Project
from .conversation import Conversation, AgentLog
from .requirement import BRDRecord, SRSRecord, DesignSpec
from .module import Module, ModuleDependency, ModuleAttempt      # Bảng DAG mới
from .code_version import CodeVersion, SourceFile
from .testing import TestCase, TestRun, TestExecution            # TestExecution mới
from .deployment import SandboxEnvironment, UserFeedback, Release
