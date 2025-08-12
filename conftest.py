# pyrefly: ignore-file
# pyright: reportGeneralTypeIssues=false
import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

os.environ["TIME_ZONE"] = "Europe/Kyiv"
django_settings = types.ModuleType("tests.django_settings")
django_settings.SECRET_KEY = "test"
django_settings.ALLOWED_HOSTS = []
django_settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
sys.modules.setdefault("tests.django_settings", django_settings)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.django_settings")

# Provide minimal stub for the external 'cognee' package
cognee_stub = types.ModuleType("cognee")
cognee_stub.__path__ = []  # mark as package so submodules can be imported
cognee_stub.add = lambda *a, **k: None
cognee_stub.cognify = lambda *a, **k: None
cognee_stub.search = lambda *a, **k: []

modules = {
    "cognee": cognee_stub,
    "cognee.modules.data.exceptions": types.ModuleType("cognee.modules.data.exceptions"),
    "cognee.modules.users.exceptions.exceptions": types.ModuleType("cognee.modules.users.exceptions.exceptions"),
    "cognee.modules.users.methods.get_default_user": types.ModuleType("cognee.modules.users.methods.get_default_user"),
    "cognee.infrastructure.databases.exceptions": types.ModuleType("cognee.infrastructure.databases.exceptions"),
    "cognee.modules.engine.operations.setup": types.ModuleType("cognee.modules.engine.operations.setup"),
}
modules["cognee.modules.data.exceptions"].DatasetNotFoundError = Exception
modules["cognee.modules.users.exceptions.exceptions"].PermissionDeniedError = Exception
modules["cognee.modules.users.methods.get_default_user"].get_default_user = lambda: None
modules["cognee.infrastructure.databases.exceptions"].DatabaseNotCreatedError = Exception
modules["cognee.modules.engine.operations.setup"].setup = lambda: None

for name, mod in modules.items():
    sys.modules.setdefault(name, mod)

infrastructure_pkg = types.ModuleType("cognee.infrastructure")
infrastructure_pkg.__path__ = []
sys.modules.setdefault("cognee.infrastructure", infrastructure_pkg)

files_pkg = types.ModuleType("cognee.infrastructure.files")
files_pkg.__path__ = []
sys.modules.setdefault("cognee.infrastructure.files", files_pkg)

# Stub heavy optional dependencies used by ai_coach
google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
google_mod.oauth2 = sys.modules.setdefault("google.oauth2", types.ModuleType("google.oauth2"))
service_account = types.ModuleType("google.oauth2.service_account")
service_account.Credentials = object
sys.modules.setdefault("google.oauth2.service_account", service_account)
oauth2_creds = types.ModuleType("google.oauth2.credentials")
oauth2_creds.Credentials = object
sys.modules.setdefault("google.oauth2.credentials", oauth2_creds)
sys.modules.setdefault("googleapiclient", types.ModuleType("googleapiclient"))
discovery_mod = types.ModuleType("googleapiclient.discovery")
discovery_mod.build = lambda *a, **k: types.SimpleNamespace(files=lambda: None)
sys.modules.setdefault("googleapiclient.discovery", discovery_mod)
http_mod = types.ModuleType("googleapiclient.http")


class DummyDownloader:
    def __init__(self, *a, **k):
        pass

    def next_chunk(self):
        return None, True


http_mod.MediaIoBaseDownload = DummyDownloader
sys.modules.setdefault("googleapiclient.http", http_mod)
google_mod.cloud = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
gcs_mod = types.ModuleType("google.cloud.storage")
gcs_mod.Client = object
sys.modules.setdefault("google.cloud.storage", gcs_mod)
google_mod.cloud.storage = gcs_mod
aiogram_mod = types.ModuleType("aiogram")
fsm_mod = types.ModuleType("aiogram.fsm")
context_mod = types.ModuleType("aiogram.fsm.context")
context_mod.FSMContext = object
sys.modules.setdefault("aiogram", aiogram_mod)
sys.modules.setdefault("aiogram.fsm", fsm_mod)
sys.modules.setdefault("aiogram.fsm.context", context_mod)
types_mod = types.ModuleType("aiogram.types")
types_mod.CallbackQuery = object
types_mod.Message = object
aiogram_mod.types = types_mod
sys.modules.setdefault("aiogram.types", types_mod)
state_mod = types.ModuleType("aiogram.fsm.state")
state_mod.State = object
state_mod.StatesGroup = object
fsm_mod.state = state_mod
sys.modules.setdefault("aiogram.fsm.state", state_mod)
services_mod = types.ModuleType("core.services")
class _DummyProfileService:
    async def get_client_by_profile_id(self, profile_id):
        return None

class _DummyWorkoutService:
    async def get_latest_subscription(self, client_profile_id):
        return None

    async def get_latest_program(self, client_profile_id):
        return None

services_mod.ProfileService = _DummyProfileService
services_mod.WorkoutService = _DummyWorkoutService
sys.modules.setdefault("core.services", services_mod)
sys.modules.setdefault("google.auth", types.ModuleType("google.auth"))
auth_exc = types.ModuleType("google.auth.exceptions")
auth_exc.DefaultCredentialsError = Exception
sys.modules.setdefault("google.auth.exceptions", auth_exc)
auth_creds = types.ModuleType("google.auth.credentials")
auth_creds.Credentials = object
sys.modules.setdefault("google.auth.credentials", auth_creds)
docx_mod = types.ModuleType("docx")


class DummyDoc:
    paragraphs = []


docx_mod.Document = lambda *a, **k: DummyDoc()
sys.modules.setdefault("docx", docx_mod)
fitz_mod = types.ModuleType("fitz")


class DummyPDF:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def __iter__(self):
        return iter([])


fitz_mod.open = lambda *a, **k: DummyPDF()
sys.modules.setdefault("fitz", fitz_mod)
sys.modules.setdefault("cognee.base_config", types.ModuleType("cognee.base_config"))
sys.modules["cognee.base_config"].get_base_config = lambda: None
cognee_stub.base_config = sys.modules["cognee.base_config"]
from cognee.base_config import get_base_config
file_utils_mod = types.ModuleType("cognee.infrastructure.files.utils")

@asynccontextmanager
async def _open_data_file(path: str, mode: str = "rb", encoding: str | None = None, **kwargs: Any):
    if ":" in path and "\\" in path:
        path = "file://" + path.replace("\\", "/")
    if path.startswith("file://"):
        parsed = urlparse(path)
        p = (parsed.path or parsed.netloc).replace("\\", "/").lstrip("/")
        if len(p) > 1 and p[1] == ":":
            p = p[1:]
        abs_path = Path(p).resolve()
        if not abs_path.exists():
            base = Path(sys.modules["cognee.base_config"].get_base_config().data_root_directory)
            abs_path = base / abs_path.name
        with open(abs_path, mode=mode, encoding=encoding, **kwargs) as f:
            yield f
    else:
        with open(path, mode=mode, encoding=encoding, **kwargs) as f:
            yield f

file_utils_mod.open_data_file = _open_data_file
sys.modules.setdefault("cognee.infrastructure.files.utils", file_utils_mod)
sys.modules.setdefault("openai", types.ModuleType("openai"))
sys.modules["openai"].AsyncOpenAI = object
loguru_mod = types.ModuleType("loguru")
loguru_mod.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    debug=lambda *a, **k: None,
    trace=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
)
sys.modules.setdefault("loguru", loguru_mod)
settings_stub = types.SimpleNamespace(
    VECTORDATABASE_URL="sqlite://",
    LOG_LEVEL="INFO",
    GDRIVE_FOLDER_ID="folder",
    GOOGLE_APPLICATION_CREDENTIALS="/tmp/creds.json",
    SPREADSHEET_ID="sheet",
    REDIS_URL="redis://localhost:6379",
    API_URL="http://localhost/",
    API_KEY="test_api_key",
    API_MAX_RETRIES=1,
    API_RETRY_INITIAL_DELAY=0,
    API_RETRY_BACKOFF_FACTOR=1,
    API_RETRY_MAX_DELAY=0,
    API_TIMEOUT=1,
)
sys.modules.setdefault("config.app_settings", types.ModuleType("config.app_settings"))
sys.modules["config.app_settings"].settings = settings_stub
logger_stub = types.ModuleType("config.logger")
logger_stub.configure_loguru = lambda: None
logger_stub.LOGGING = {}
sys.modules.setdefault("config.logger", logger_stub)
crypto_mod = types.ModuleType("cryptography")
crypto_mod.fernet = types.ModuleType("cryptography.fernet")
crypto_mod.fernet.Fernet = object
sys.modules.setdefault("cryptography", crypto_mod)
sys.modules.setdefault("cryptography.fernet", crypto_mod.fernet)
sqlalchemy_mod = types.ModuleType("sqlalchemy")
sqlalchemy_mod.schema = types.ModuleType("sqlalchemy.schema")
sqlalchemy_mod.exc = types.ModuleType("sqlalchemy.exc")
sqlalchemy_mod.exc.SAWarning = type("SAWarning", (Warning,), {})
sys.modules.setdefault("sqlalchemy", sqlalchemy_mod)
sys.modules.setdefault("sqlalchemy.schema", sqlalchemy_mod.schema)
sys.modules.setdefault("sqlalchemy.exc", sqlalchemy_mod.exc)
redis_async_mod = types.ModuleType("redis.asyncio")


class DummyRedis:
    async def sadd(self, *a, **k):
        pass

    async def sismember(self, *a, **k):
        return False


redis_async_mod.Redis = type("Redis", (), {"from_url": lambda *a, **k: DummyRedis()})
sys.modules.setdefault("redis.asyncio", redis_async_mod)

django = types.SimpleNamespace(setup=lambda: None)

env_defaults = {
    "API_KEY": "test_api_key",
    "API_URL": "http://localhost/",
    "BOT_TOKEN": "bot_token",
    "BOT_LINK": "http://bot",
    "WEBHOOK_HOST": "http://localhost",
    "WEBHOOK_PORT": "8000",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json",
    "SPREADSHEET_ID": "sheet",
    "TG_SUPPORT_CONTACT": "@support",
    "PUBLIC_OFFER": "http://offer",
    "PRIVACY_POLICY": "http://privacy",
    "EMAIL": "test@example.com",
    "ADMIN_ID": "1",
    "PAYMENT_PRIVATE_KEY": "priv",
    "PAYMENT_PUB_KEY": "pub",
    "CHECKOUT_URL": "http://checkout",
    "POSTGRES_PASSWORD": "password",
    "SECRET_KEY": "test",
    "AI_COACH_URL": "http://localhost/",
}
for key, value in env_defaults.items():
    os.environ.setdefault(key, value)


django.setup()
