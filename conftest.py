# pyrefly: ignore-file
# pyright: reportGeneralTypeIssues=false
import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

os.environ["TIME_ZONE"] = "Europe/Kyiv"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")

# Provide minimal stub for the external 'cognee' package
cognee_stub = types.ModuleType("cognee")
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
    "cognee.base_config": types.ModuleType("cognee.base_config"),
    "cognee.infrastructure": types.ModuleType("cognee.infrastructure"),
    "cognee.infrastructure.files": types.ModuleType("cognee.infrastructure.files"),
}
modules["cognee.modules.data.exceptions"].DatasetNotFoundError = Exception
modules["cognee.modules.users.exceptions.exceptions"].PermissionDeniedError = Exception
modules["cognee.modules.users.methods.get_default_user"].get_default_user = lambda: None
modules["cognee.infrastructure.databases.exceptions"].DatabaseNotCreatedError = Exception
modules["cognee.modules.engine.operations.setup"].setup = lambda: None
modules["cognee.base_config"].get_base_config = lambda: types.SimpleNamespace(data_root_directory=".")
cognee_stub.base_config = modules["cognee.base_config"]
files_utils_mod = types.ModuleType("cognee.infrastructure.files.utils")


@asynccontextmanager
async def open_data_file(uri: str, mode: str = "r"):
    base = Path(modules["cognee.base_config"].get_base_config().data_root_directory)
    name = uri.split("/")[-1].split("\\")[-1]
    with open(base / name, mode) as f:
        yield f


files_utils_mod.open_data_file = open_data_file
modules["cognee.infrastructure.files.utils"] = files_utils_mod

for name, mod in modules.items():
    sys.modules.setdefault(name, mod)

# Stub heavy optional dependencies used by ai_coach
google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.oauth2", types.ModuleType("google.oauth2"))
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
google_cloud = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
google_mod.cloud = google_cloud
gcs_mod = types.ModuleType("google.cloud.storage")
gcs_mod.Client = object
google_cloud.storage = gcs_mod
sys.modules.setdefault("google.cloud.storage", gcs_mod)
sys.modules.setdefault("google.auth", types.ModuleType("google.auth"))
auth_exc = types.ModuleType("google.auth.exceptions")
auth_exc.DefaultCredentialsError = Exception
sys.modules.setdefault("google.auth.exceptions", auth_exc)
auth_creds = types.ModuleType("google.auth.credentials")
auth_creds.Credentials = object
sys.modules.setdefault("google.auth.credentials", auth_creds)
gspread_mod = types.ModuleType("gspread")
gspread_mod.Client = object
gspread_mod.Worksheet = object
gspread_mod.authorize = lambda *a, **k: gspread_mod.Client()
gspread_mod.utils = types.SimpleNamespace(ValueInputOption=types.SimpleNamespace(user_entered="USER_ENTERED"))
sys.modules.setdefault("gspread", gspread_mod)
sys.modules.setdefault("gspread.utils", gspread_mod.utils)
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
sys.modules.setdefault("openai", types.ModuleType("openai"))
sys.modules["openai"].AsyncOpenAI = object
loguru_mod = types.ModuleType("loguru")
loguru_mod.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    debug=lambda *a, **k: None,
    trace=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    exception=lambda *a, **k: None,
)
sys.modules.setdefault("loguru", loguru_mod)
settings_stub = types.SimpleNamespace(
    VECTORDATABASE_URL="sqlite://",
    LOG_LEVEL="INFO",
    GDRIVE_FOLDER_ID="folder",
    GOOGLE_APPLICATION_CREDENTIALS="/tmp/creds.json",
    REDIS_URL="redis://localhost:6379",
    API_URL="http://localhost/",
    API_KEY="test_api_key",
    API_MAX_RETRIES=2,
    API_RETRY_INITIAL_DELAY=0,
    API_RETRY_BACKOFF_FACTOR=1,
    API_RETRY_MAX_DELAY=0,
    API_TIMEOUT=1,
    SPREADSHEET_ID="sheet",
)
sys.modules.setdefault("config.app_settings", types.ModuleType("config.app_settings"))
sys.modules["config.app_settings"].settings = settings_stub
logger_stub = types.ModuleType("config.logger")
logger_stub.configure_loguru = lambda: None
logger_stub.LOGGING = {}
sys.modules.setdefault("config.logger", logger_stub)
pydantic_mod = types.ModuleType("pydantic")
pydantic_mod.BaseModel = object
pydantic_mod.Field = lambda *a, **k: None
pydantic_mod.field_validator = lambda *a, **k: (lambda x: x)
pydantic_mod.condecimal = lambda *a, **k: float
pydantic_mod.ConfigDict = dict
pydantic_mod.create_model = lambda name, **fields: type(name, (object,), fields)
pydantic_mod.ValidationError = Exception
sys.modules.setdefault("pydantic", pydantic_mod)
core_mod = types.ModuleType("pydantic_core")
core_mod.ValidationError = Exception
sys.modules.setdefault("pydantic_core", core_mod)
redis_mod = types.ModuleType("redis")
redis_mod.exceptions = types.ModuleType("redis.exceptions")
redis_mod.exceptions.RedisError = Exception
sys.modules.setdefault("redis", redis_mod)
sys.modules.setdefault("redis.exceptions", redis_mod.exceptions)
yaml_mod = types.ModuleType("yaml")
yaml_mod.safe_load = lambda *a, **k: {}
sys.modules.setdefault("yaml", yaml_mod)
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
    async def close(self):
        pass

    async def ping(self):
        return True

    async def hget(self, *a, **k):
        return None

    async def hset(self, *a, **k):
        pass

    async def hdel(self, *a, **k):
        pass

    async def hgetall(self, *a, **k):
        return {}

    async def sadd(self, *a, **k):
        pass

    async def sismember(self, *a, **k):
        return False


redis_async_mod.Redis = DummyRedis
redis_async_mod.from_url = lambda *a, **k: DummyRedis()
sys.modules.setdefault("redis.asyncio", redis_async_mod)
httpx_mod = types.ModuleType("httpx")


class HTTPError(Exception):
    pass


class HTTPStatusError(HTTPError):
    def __init__(self, message: str, request: Any = None, response: Any = None):
        super().__init__(message)
        self.request = request
        self.response = response


class AsyncClient:
    def __init__(self, *a, **k):
        self.timeout = k.get("timeout")

    async def request(self, *a, **k):
        return types.SimpleNamespace(status_code=200, headers={}, json=lambda: {}, text="", is_success=True)

    async def aclose(self):
        pass


class Request:
    def __init__(self, *a, **k):
        pass


class Response:
    pass


class DecodingError(Exception):
    pass


httpx_mod.AsyncClient = AsyncClient
httpx_mod.HTTPError = HTTPError
httpx_mod.HTTPStatusError = HTTPStatusError
httpx_mod.Request = Request
httpx_mod.Response = Response
httpx_mod.DecodingError = DecodingError
sys.modules.setdefault("httpx", httpx_mod)

aiogram_mod = types.ModuleType("aiogram")
aiogram_mod.Bot = type("Bot", (), {})
aiogram_mod.exceptions = types.SimpleNamespace(TelegramBadRequest=Exception)
aiogram_mod.fsm = types.SimpleNamespace(
    context=types.SimpleNamespace(FSMContext=type("FSMContext", (), {})),
    state=types.SimpleNamespace(State=type("State", (), {}), StatesGroup=type("StatesGroup", (), {})),
)
aiogram_mod.types = types.SimpleNamespace(
    Message=type("Message", (), {
        "answer": lambda *a, **k: None,
        "answer_photo": lambda *a, **k: None,
        "answer_document": lambda *a, **k: None,
        "answer_video": lambda *a, **k: None,
    }),
    CallbackQuery=type("CallbackQuery", (), {"answer": lambda *a, **k: None, "message": None}),
    BotCommand=object,
    InlineKeyboardButton=type("InlineKeyboardButton", (), {}),
)
sys.modules.setdefault("aiogram", aiogram_mod)
sys.modules.setdefault("aiogram.exceptions", aiogram_mod.exceptions)
sys.modules.setdefault("aiogram.fsm", aiogram_mod.fsm)
sys.modules.setdefault("aiogram.fsm.context", aiogram_mod.fsm.context)
sys.modules.setdefault("aiogram.fsm.state", aiogram_mod.fsm.state)
sys.modules.setdefault("aiogram.types", aiogram_mod.types)
sys.modules.setdefault("aiogram.client", types.ModuleType("aiogram.client"))
client_default = types.ModuleType("aiogram.client.default")
client_default.DefaultBotProperties = type("DefaultBotProperties", (), {})
aiogram_mod.client = types.SimpleNamespace(default=client_default)
sys.modules.setdefault("aiogram.client.default", client_default)
django_mod = types.ModuleType("django")
django_conf = types.ModuleType("django.conf")
django_conf.settings = settings_stub
django_mod.conf = django_conf
django_mod.setup = lambda: None
sys.modules.setdefault("django", django_mod)
sys.modules.setdefault("django.conf", django_conf)

bot_texts = types.ModuleType("bot.texts")
bot_texts.TextManager = types.SimpleNamespace(messages={}, buttons={}, commands={})
bot_texts.msg_text = lambda key, lang=None: key
bot_texts.btn_text = lambda key, lang=None: key
sys.modules.setdefault("bot.texts", bot_texts)
sys.modules.setdefault("bot.texts.text_manager", bot_texts)
resources_mod = types.ModuleType("bot.texts.resources")
resources_mod.ButtonText = dict
resources_mod.MessageText = dict
sys.modules.setdefault("bot.texts.resources", resources_mod)

di_mod = types.ModuleType("dependency_injector")
di_wiring = types.ModuleType("dependency_injector.wiring")
di_wiring.inject = lambda *a, **k: (lambda f: f)


class Provide:
    def __class_getitem__(cls, item):
        return cls


di_wiring.Provide = Provide
di_mod.wiring = di_wiring
sys.modules.setdefault("dependency_injector", di_mod)
sys.modules.setdefault("dependency_injector.wiring", di_wiring)
di_containers = types.ModuleType("dependency_injector.containers")
di_containers.DeclarativeContainer = type("DeclarativeContainer", (), {})
di_providers = types.ModuleType("dependency_injector.providers")
di_providers.Factory = lambda *a, **k: None
di_providers.Singleton = lambda *a, **k: None
di_providers.Callable = lambda *a, **k: None
di_providers.Configuration = lambda *a, **k: types.SimpleNamespace(bot_token="", parse_mode="")
di_mod.containers = di_containers
di_mod.providers = di_providers
sys.modules.setdefault("dependency_injector.containers", di_containers)
sys.modules.setdefault("dependency_injector.providers", di_providers)

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

django_mod.setup()
