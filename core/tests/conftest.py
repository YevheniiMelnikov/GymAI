# pyrefly: ignore-file
# pyright: reportGeneralTypeIssues=false
import inspect
import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Generic, TypeVar

import pytest

TESTS_DIR: Path = Path(__file__).resolve().parent
CORE_DIR: Path = TESTS_DIR.parent
ROOT_DIR: Path = CORE_DIR.parent
python_path: list[str] = sys.path
if str(ROOT_DIR) not in python_path:
    python_path.append(str(ROOT_DIR))

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

# Lightweight stubs for frequently missing dependencies

# pydantic stub
pydantic_mod = types.ModuleType("pydantic")


class ValidationError(Exception):
    pass


class BaseModel:
    def __init__(self, **data: any) -> None:
        for name, value in self.__class__.__dict__.items():
            if name.startswith("_") or callable(value):
                continue
            setattr(self, name, value)
        for k, v in data.items():
            setattr(self, k, v)
        # run field validators
        for attr in dir(self.__class__):
            fn = getattr(self.__class__, attr)
            meta = getattr(fn, "_field_validator", None)
            if meta:
                fields, mode = meta
                for field in fields:
                    current = getattr(self, field, None)
                    params = len(inspect.signature(fn).parameters)
                    info = types.SimpleNamespace(data=data)
                    if params == 3:
                        current = fn(self.__class__, current, info)
                    else:
                        current = fn(self.__class__, current)
                    setattr(self, field, current)
        # run model validators (after)
        for attr in dir(self.__class__):
            fn = getattr(self.__class__, attr)
            if getattr(fn, "_model_validator", None) == "after":
                fn(self)

    @classmethod
    def model_validate(cls, data: dict[str, any]) -> "BaseModel":
        return cls(**data)

    def model_dump(self, *a: any, **k: any) -> dict[str, any]:
        data = dict(self.__dict__)
        exclude = k.get("exclude")
        if isinstance(exclude, set):
            for key in exclude:
                data.pop(key, None)
        if k.get("exclude_none"):
            data = {k: v for k, v in data.items() if v is not None}
        return data

    def model_copy(self, *, update: dict[str, any] | None = None) -> "BaseModel":
        data = self.model_dump()
        if update:
            data.update(update)
        return self.__class__(**data)


def condecimal(*_a: any, **_k: any) -> type[float]:
    return float


class ConfigDict(dict[str, any]):
    pass


def Field(default: any = None, **_: any) -> any:
    return default


def field_validator(*fields: str, mode: str = "after"):
    def decorator(f: any) -> any:
        f._field_validator = (fields, mode)
        return f

    return decorator


def model_validator(*, mode: str = "after"):
    def decorator(f: any) -> any:
        f._model_validator = mode
        return f

    return decorator


pydantic_mod.BaseModel = BaseModel
pydantic_mod.Field = Field
pydantic_mod.ValidationError = ValidationError
pydantic_mod.field_validator = field_validator
pydantic_mod.model_validator = model_validator
pydantic_mod.condecimal = condecimal
pydantic_mod.ConfigDict = ConfigDict

sys.modules.setdefault("pydantic", pydantic_mod)

# pydantic_settings stub
pydantic_settings_mod = types.ModuleType("pydantic_settings")


class BaseSettings(BaseModel):
    pass


pydantic_settings_mod.BaseSettings = BaseSettings
sys.modules.setdefault("pydantic_settings", pydantic_settings_mod)

# loguru stub
loguru_mod = types.ModuleType("loguru")


class _Logger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def success(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


loguru_mod.logger = _Logger()
sys.modules.setdefault("loguru", loguru_mod)

aiohttp_mod = types.ModuleType("aiohttp")
aiohttp_mod.ClientSession = object
sys.modules.setdefault("aiohttp", aiohttp_mod)

pydantic_ai_mod = types.ModuleType("pydantic_ai")


class ModelRetry(Exception):
    pass


class Agent:
    def __init__(self, *a, **k):
        self.system_prompt = lambda f: f
        self.instructions = lambda f: f

    async def run(self, *a, **k):
        output = k.get("output_type")
        return output() if output else None


T_deps = TypeVar("T_deps")


class RunContext(Generic[T_deps]):
    def __init__(self, deps: T_deps):
        self.deps = deps


pydantic_ai_mod.Agent = Agent
pydantic_ai_mod.RunContext = RunContext
pydantic_ai_mod.ModelRetry = ModelRetry
sys.modules.setdefault("pydantic_ai", pydantic_ai_mod)

settings_mod = types.ModuleType("pydantic_ai.settings")


class ModelSettings:
    def __init__(self, **_k):
        pass


settings_mod.ModelSettings = ModelSettings
sys.modules.setdefault("pydantic_ai.settings", settings_mod)

messages_mod = types.ModuleType("pydantic_ai.messages")


class ModelMessage:  # pragma: no cover - simple container
    pass


class ModelRequest:
    @staticmethod
    def user_text_prompt(text: str) -> str:
        return text


class ModelResponse:  # pragma: no cover - simple container
    def __init__(self, parts: list[Any] | None = None):
        self.parts = parts or []


class TextPart:  # pragma: no cover - simple container
    def __init__(self, content: str):
        self.content = content


messages_mod.ModelMessage = ModelMessage
messages_mod.ModelRequest = ModelRequest
messages_mod.ModelResponse = ModelResponse
messages_mod.TextPart = TextPart
sys.modules.setdefault("pydantic_ai.messages", messages_mod)

models_mod = types.ModuleType("pydantic_ai.models")
openai_mod = types.ModuleType("pydantic_ai.models.openai")


class OpenAIChatModel:  # pragma: no cover - minimal stub
    def __init__(self, *a, **k):
        self.client = None


openai_mod.OpenAIChatModel = OpenAIChatModel
models_mod.openai = openai_mod
sys.modules.setdefault("pydantic_ai.models", models_mod)
sys.modules.setdefault("pydantic_ai.models.openai", openai_mod)

toolsets_mod = types.ModuleType("pydantic_ai.toolsets")
function_mod = types.ModuleType("pydantic_ai.toolsets.function")


class FunctionToolset:
    def tool(self, func: Any | None = None, **kwargs: Any):  # pragma: no cover - trivial
        if func is None:

            def decorator(f: Any) -> Any:
                return f

            return decorator
        return func


function_mod.FunctionToolset = FunctionToolset
toolsets_mod.function = function_mod
sys.modules.setdefault("pydantic_ai.toolsets", toolsets_mod)
sys.modules.setdefault("pydantic_ai.toolsets.function", function_mod)
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
    success=lambda *a, **k: None,
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
    API_MAX_CONNECTIONS=100,
    API_MAX_KEEPALIVE_CONNECTIONS=20,
    SPREADSHEET_ID="sheet",
    SECRET_KEY="test",
    DB_NAME="postgres",
    DB_USER="postgres",
    DB_PASSWORD="password",
    DB_HOST="localhost",
    DB_PORT="5432",
    SITE_NAME="Test",
    ALLOWED_HOSTS=["localhost"],
    TIME_ZONE="Europe/Kyiv",
    DEFAULT_LANG="en",
    PAYMENT_PRIVATE_KEY="priv",
    PAYMENT_PUB_KEY="pub",
    WEBHOOK_PATH="/telegram/webhook",
    AI_COACH_REFRESH_USER="admin",
    AI_COACH_REFRESH_PASSWORD="pass",
)
sys.modules["config.app_settings"] = types.ModuleType("config.app_settings")
sys.modules["config.app_settings"].settings = settings_stub
logger_stub = types.ModuleType("config.logger")
logger_stub.configure_loguru = lambda: None
logger_stub.LOGGING = {}
sys.modules.setdefault("config.logger", logger_stub)
redis_mod = types.ModuleType("redis")
redis_mod.exceptions = types.ModuleType("redis.exceptions")
redis_mod.exceptions.RedisError = Exception
sys.modules.setdefault("redis", redis_mod)


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    mod = sys.modules.setdefault("config.app_settings", types.ModuleType("config.app_settings"))
    current = getattr(mod, "settings", types.SimpleNamespace())
    for k, v in settings_stub.__dict__.items():
        setattr(current, k, v)
    mod.settings = current


sys.modules.setdefault("redis.exceptions", redis_mod.exceptions)
yaml_mod = types.ModuleType("yaml")
yaml_mod.safe_load = lambda *a, **k: {}
yaml_mod.SafeLoader = object
sys.modules.setdefault("yaml", yaml_mod)
crypto_mod = types.ModuleType("cryptography")
crypto_mod.fernet = types.ModuleType("cryptography.fernet")


class _Fernet:
    def __init__(self, key: bytes):
        self.key = key

    def encrypt(self, data: bytes) -> bytes:
        return data[::-1]

    def decrypt(self, token: bytes) -> bytes:
        return token[::-1]


crypto_mod.fernet.Fernet = _Fernet
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


class DummyPipeline:
    def __init__(self, client: "DummyRedis") -> None:
        self._client = client
        self._result = False

    async def watch(self, *_a, **_k):  # type: ignore[no-untyped-def]
        return None

    async def reset(self):  # type: ignore[no-untyped-def]
        self._result = False

    def multi(self):  # type: ignore[no-untyped-def]
        self._result = False

    def pexpire(self, key: str, ttl_ms: int):  # type: ignore[no-untyped-def]
        if key in self._client.storage:
            self._result = True

    async def execute(self):  # type: ignore[no-untyped-def]
        return [self._result]


class DummyRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    @classmethod
    def from_url(cls, *a, **k):
        return cls()

    def pipeline(self):  # type: ignore[no-untyped-def]
        return DummyPipeline(self)

    async def set(self, key: str, value: str, ex=None, nx: bool = False):  # type: ignore[no-untyped-def]
        if nx and key in self.storage:
            return False
        self.storage[key] = value
        return True

    async def get(self, key: str):  # type: ignore[no-untyped-def]
        return self.storage.get(key)

    async def exists(self, key: str):  # type: ignore[no-untyped-def]
        return 1 if key in self.storage else 0

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

    async def expire(self, *a, **k):
        return None


redis_async_mod.Redis = DummyRedis
redis_async_mod.from_url = lambda *a, **k: DummyRedis()
redis_async_client_mod = types.ModuleType("redis.asyncio.client")
redis_async_client_mod.Pipeline = DummyPipeline
sys.modules.setdefault("redis.asyncio.client", redis_async_client_mod)
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
        self.is_closed = False

    async def __aenter__(self):  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        await self.aclose()

    async def request(self, method, url, json=None, headers=None, **kwargs):  # type: ignore[no-untyped-def]
        from ai_coach.agent import CoachAgent
        from ai_coach.agent import QAResponse

        json = json or {}
        mode = json.get("mode")
        if url.endswith("/ask/"):
            if mode == "ask_ai":
                try:
                    result = await CoachAgent.answer_question(json.get("prompt", ""), deps=None)
                    if isinstance(result, QAResponse):
                        return types.SimpleNamespace(
                            status_code=200,
                            headers={},
                            json=lambda: {"answer": result.answer, "sources": result.sources},
                            text="",
                            is_success=True,
                        )
                except Exception:
                    return types.SimpleNamespace(
                        status_code=503, headers={}, json=lambda: {}, text="", is_success=False
                    )
            elif mode == "update" and "plan_type" not in json:
                return types.SimpleNamespace(status_code=422, headers={}, json=lambda: {}, text="", is_success=False)
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: {"id": 1}, text="", is_success=True)
        if url.endswith("/knowledge/refresh/"):
            import base64
            from config.app_settings import settings as cfg_settings

            auth = (headers or {}).get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    user, pwd = base64.b64decode(auth[6:]).decode().split(":", 1)
                except Exception:  # pragma: no cover - bad header
                    user, pwd = "", ""
            else:
                user, pwd = "", ""
            if user == getattr(cfg_settings, "AI_COACH_REFRESH_USER", "") and pwd == getattr(
                cfg_settings, "AI_COACH_REFRESH_PASSWORD", ""
            ):
                from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

                await KnowledgeBase.refresh()
                return types.SimpleNamespace(
                    status_code=200,
                    headers={},
                    json=lambda: {"status": "ok"},
                    text="",
                    is_success=True,
                )
            return types.SimpleNamespace(status_code=401, headers={}, json=lambda: {}, text="", is_success=False)
        return types.SimpleNamespace(status_code=200, headers={}, json=lambda: {}, text="", is_success=True)

    async def aclose(self):  # pragma: no cover - trivial
        self.is_closed = True

    async def post(self, url, *a, **k):  # type: ignore[no-untyped-def]
        return await self.request("POST", url, *a, **k)


class Request:
    def __init__(self, *a, **k):
        pass


class Response:
    pass


class DecodingError(Exception):
    pass


class Limits:
    def __init__(self, *a, **k):
        pass


httpx_mod.AsyncClient = AsyncClient
httpx_mod.HTTPError = HTTPError
httpx_mod.HTTPStatusError = HTTPStatusError
httpx_mod.Request = Request
httpx_mod.Response = Response
httpx_mod.DecodingError = DecodingError
httpx_mod.Limits = Limits
sys.modules.setdefault("httpx", httpx_mod)

aiogram_mod = types.ModuleType("aiogram")
aiogram_mod.Bot = type("Bot", (), {})
aiogram_mod.exceptions = types.SimpleNamespace(TelegramBadRequest=Exception)
aiogram_mod.fsm = types.SimpleNamespace(
    context=types.SimpleNamespace(FSMContext=type("FSMContext", (), {})),
    state=types.SimpleNamespace(State=type("State", (), {}), StatesGroup=type("StatesGroup", (), {})),
)
aiogram_mod.types = types.SimpleNamespace(
    Message=type(
        "Message",
        (),
        {
            "answer": lambda *a, **k: None,
            "answer_photo": lambda *a, **k: None,
            "answer_document": lambda *a, **k: None,
            "answer_video": lambda *a, **k: None,
        },
    ),
    CallbackQuery=type("CallbackQuery", (), {"answer": lambda *a, **k: None, "message": None}),
    BotCommand=object,
    InlineKeyboardButton=type("InlineKeyboardButton", (), {"__init__": lambda self, *a, **k: None}),
    InlineKeyboardMarkup=type("InlineKeyboardMarkup", (), {"__init__": lambda self, *a, **k: None}),
    WebAppInfo=type("WebAppInfo", (), {}),
    FSInputFile=object,
    InputFile=object,
)
aiogram_mod.enums = types.SimpleNamespace(ParseMode=type("ParseMode", (), {}))
sys.modules.setdefault("aiogram", aiogram_mod)
sys.modules.setdefault("aiogram.exceptions", aiogram_mod.exceptions)
sys.modules.setdefault("aiogram.fsm", aiogram_mod.fsm)
sys.modules.setdefault("aiogram.fsm.context", aiogram_mod.fsm.context)
sys.modules.setdefault("aiogram.fsm.state", aiogram_mod.fsm.state)
sys.modules.setdefault("aiogram.types", aiogram_mod.types)
sys.modules.setdefault("aiogram.enums", aiogram_mod.enums)
sys.modules.setdefault("aiogram.client", types.ModuleType("aiogram.client"))
client_default = types.ModuleType("aiogram.client.default")
client_default.DefaultBotProperties = type("DefaultBotProperties", (), {})
aiogram_mod.client = types.SimpleNamespace(default=client_default)
sys.modules.setdefault("aiogram.client.default", client_default)
aiogram_utils = types.ModuleType("aiogram.utils")
keyboard_mod = types.ModuleType("aiogram.utils.keyboard")
keyboard_mod.InlineKeyboardBuilder = type("InlineKeyboardBuilder", (), {})
aiogram_utils.keyboard = keyboard_mod
sys.modules.setdefault("aiogram.utils", aiogram_utils)
sys.modules.setdefault("aiogram.utils.keyboard", keyboard_mod)
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

try:
    import dependency_injector  # noqa: F401
    import dependency_injector.providers as di_providers  # type: ignore

    sys.modules.setdefault("dependency_injector.providers", di_providers)
except Exception:  # pragma: no cover - fallback stubs
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

    def _provider(obj, *a, **k):  # pragma: no cover - simple stub
        return lambda *args, **kwargs: obj

    di_providers.Factory = _provider
    di_providers.Singleton = _provider
    di_providers.Callable = _provider
    di_providers.Resource = _provider
    di_providers.Configuration = lambda *a, **k: types.SimpleNamespace(bot_token="", parse_mode="")
    di_mod.containers = di_containers
    di_mod.providers = di_providers
    sys.modules.setdefault("dependency_injector.containers", di_containers)
    sys.modules.setdefault("dependency_injector.providers", di_providers)

# Additional lightweight stubs for Django, FastAPI, and DRF components
django_core = types.ModuleType("django.core")
django_cache_mod = types.ModuleType("django.core.cache")


class _Cache:
    store: dict[str, Any] = {}

    def get_or_set(self, key, default, timeout=None):
        if key not in self.store:
            self.store[key] = default()
        return self.store[key]

    def delete(self, key):
        self.store.pop(key, None)

    def delete_many(self, keys):
        for k in keys:
            self.delete(k)


cache = _Cache()
django_cache_mod.cache = cache
sys.modules.setdefault("django.core", django_core)
sys.modules.setdefault("django.core.cache", django_cache_mod)

django_utils = types.ModuleType("django.utils")
django_utils_decorators = types.ModuleType("django.utils.decorators")
django_utils_decorators.method_decorator = lambda *a, **k: (lambda f: f)
sys.modules.setdefault("django.utils", django_utils)
sys.modules.setdefault("django.utils.decorators", django_utils_decorators)

django_views = types.ModuleType("django.views")
django_views_decorators = types.ModuleType("django.views.decorators")
django_cache_page = types.ModuleType("django.views.decorators.cache")
django_cache_page.cache_page = lambda *a, **k: (lambda f: f)
sys.modules.setdefault("django.views", django_views)
sys.modules.setdefault("django.views.decorators", django_views_decorators)
sys.modules.setdefault("django.views.decorators.cache", django_cache_page)
django_http = types.ModuleType("django.views.decorators.http")
django_http.require_GET = lambda f: f
sys.modules.setdefault("django.views.decorators.http", django_http)

django_test = types.ModuleType("django.test")


class DummyHttpResponse:
    def __init__(self, location: str):
        self.status_code = 302
        self._location = location

    def __getitem__(self, key: str) -> str:
        if key == "Location":
            return self._location
        raise KeyError(key)


class DummyClient:
    def get(self, path: str) -> DummyHttpResponse:
        query = path.split("?", 1)[1] if "?" in path else ""
        location = "/webapp/" + ("?" + query if query else "")
        return DummyHttpResponse(location)


django_test.Client = DummyClient
sys.modules.setdefault("django.test", django_test)

asgiref_mod = types.ModuleType("asgiref")
asgiref_sync = types.ModuleType("asgiref.sync")
asgiref_sync.sync_to_async = lambda f, *a, **k: f
sys.modules.setdefault("asgiref", asgiref_mod)
sys.modules.setdefault("asgiref.sync", asgiref_sync)

django_http = types.ModuleType("django.http")


class HttpRequest:
    method = "GET"
    GET: dict[str, Any] = {}
    POST: dict[str, Any] = {}


django_http.HttpRequest = HttpRequest


class JsonResponse(dict):
    def __init__(self, data=None, status=200):
        super().__init__(data or {})
        self.status_code = status


class HttpResponse(DummyHttpResponse):
    def __init__(self, location: str = "", status: int = 200):
        self.status_code = status
        self._location = location


django_http.JsonResponse = JsonResponse
django_http.HttpResponse = HttpResponse
sys.modules.setdefault("django.http", django_http)

django_db = types.ModuleType("django.db")
django_db_models = types.ModuleType("django.db.models")


class QuerySet(list):
    def filter(self, **kwargs):
        return QuerySet([o for o in self if all(getattr(o, k) == v for k, v in kwargs.items())])

    def values_list(self, field, flat=False):
        return [getattr(o, field) for o in self]

    def select_related(self, *a, **k):
        return self

    def all(self):  # pragma: no cover - mimic Django
        return self


django_db_models.QuerySet = QuerySet
django_db_models.Model = object
sys.modules.setdefault("django.db", django_db)
sys.modules.setdefault("django.db.models", django_db_models)

fastapi_mod = types.ModuleType("fastapi")


class FastAPI:
    def __init__(self, *a, **k):
        pass

    def get(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def post(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


fastapi_mod.FastAPI = FastAPI


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


def Depends(dep: Any) -> Any:
    return dep


class Request:  # pragma: no cover - simple container
    pass


fastapi_mod.HTTPException = HTTPException
fastapi_mod.Depends = Depends
fastapi_mod.Request = Request
fastapi_security = types.ModuleType("fastapi.security")
fastapi_security.HTTPBasic = object


class HTTPBasicCredentials:
    def __init__(self, username: str = "", password: str = "") -> None:
        self.username = username
        self.password = password


fastapi_security.HTTPBasicCredentials = HTTPBasicCredentials
sys.modules.setdefault("fastapi", fastapi_mod)
sys.modules.setdefault("fastapi.security", fastapi_security)
fastapi_testclient = types.ModuleType("fastapi.testclient")


class TestClient:
    def __init__(self, app: Any) -> None:
        self.app = app

    def __enter__(self) -> "TestClient":  # pragma: no cover - context manager
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - context manager
        return None

    def post(self, url: str, json: dict | None = None):
        from ai_coach import api as _api
        from ai_coach.api import ask
        from ai_coach.schemas import AICoachRequest
        from config.app_settings import settings as cfg_settings
        import asyncio
        import types as _types

        _api.settings = cfg_settings
        data = AICoachRequest(**(json or {}))
        result = asyncio.run(ask(data, _types.SimpleNamespace()))
        return _types.SimpleNamespace(status_code=200, json=lambda: result)


fastapi_testclient.TestClient = TestClient
sys.modules.setdefault("fastapi.testclient", fastapi_testclient)

rest_framework = types.ModuleType("rest_framework")
rf_views = types.ModuleType("rest_framework.views")


class APIView:
    pass


rf_views.APIView = APIView
rf_generics = types.ModuleType("rest_framework.generics")


class ListAPIView(APIView):
    pass


class RetrieveUpdateAPIView(APIView):
    pass


class CreateAPIView(APIView):
    pass


rf_generics.ListAPIView = ListAPIView
rf_generics.RetrieveUpdateAPIView = RetrieveUpdateAPIView
rf_generics.CreateAPIView = CreateAPIView
rf_permissions = types.ModuleType("rest_framework.permissions")
rf_permissions.AllowAny = object
rf_serializers = types.ModuleType("rest_framework.serializers")


class _BaseSerializer:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass


class _ModelSerializer(_BaseSerializer):
    pass


rf_serializers.BaseSerializer = _BaseSerializer
rf_serializers.ModelSerializer = _ModelSerializer
rf_status = types.ModuleType("rest_framework.status")
rf_status.HTTP_200_OK = 200
rf_status.HTTP_400_BAD_REQUEST = 400
rf_exceptions = types.ModuleType("rest_framework.exceptions")
rf_exceptions.NotFound = Exception
rf_exceptions.ValidationError = Exception
rest_framework.views = rf_views
rest_framework.generics = rf_generics
rest_framework.permissions = rf_permissions
rest_framework.serializers = rf_serializers
rest_framework.status = rf_status
rest_framework.exceptions = rf_exceptions
sys.modules.setdefault("rest_framework", rest_framework)
sys.modules.setdefault("rest_framework.views", rf_views)
sys.modules.setdefault("rest_framework.generics", rf_generics)
sys.modules.setdefault("rest_framework.permissions", rf_permissions)
sys.modules.setdefault("rest_framework.serializers", rf_serializers)
sys.modules.setdefault("rest_framework.status", rf_status)
sys.modules.setdefault("rest_framework.exceptions", rf_exceptions)

rf_api_key = types.ModuleType("rest_framework_api_key")
rf_api_key_perm = types.ModuleType("rest_framework_api_key.permissions")
rf_api_key_perm.HasAPIKey = object
rf_api_key.permissions = rf_api_key_perm
sys.modules.setdefault("rest_framework_api_key", rf_api_key)
sys.modules.setdefault("rest_framework_api_key.permissions", rf_api_key_perm)

payments_models = types.ModuleType("apps.payments.models")


class Payment:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


payments_models.Payment = Payment
sys.modules.setdefault("apps.payments.models", payments_models)

payments_repos = types.ModuleType("apps.payments.repos")


class PaymentRepository:
    @staticmethod
    def base_qs():
        return []

    @staticmethod
    def filter(qs, *, status=None, order_id=None):
        return [
            p for p in qs if (status is None or p.status == status) and (order_id is None or p.order_id == order_id)
        ]


payments_repos.PaymentRepository = PaymentRepository
sys.modules.setdefault("apps.payments.repos", payments_repos)

payments_serializers = types.ModuleType("apps.payments.serializers")


class PaymentSerializer:
    pass


payments_serializers.PaymentSerializer = PaymentSerializer
sys.modules.setdefault("apps.payments.serializers", payments_serializers)

payments_tasks = types.ModuleType("apps.payments.tasks")
payments_tasks.process_payment_webhook = types.SimpleNamespace(delay=lambda **k: None)
payments_tasks.send_payment_message = types.SimpleNamespace(delay=lambda **k: None)
sys.modules.setdefault("apps.payments.tasks", payments_tasks)

profiles_models = types.ModuleType("apps.profiles.models")


class ClientProfile:
    pass


class Profile:
    pass


class CoachProfile:
    pass


profiles_models.ClientProfile = ClientProfile
profiles_models.Profile = Profile
profiles_models.CoachProfile = CoachProfile
sys.modules.setdefault("apps.profiles.models", profiles_models)

bot_utils_bot = types.ModuleType("bot.utils.bot")


async def _noop_async(*a: Any, **k: Any) -> None:
    return None


bot_utils_bot.answer_msg = _noop_async
bot_utils_bot.del_msg = _noop_async
bot_utils_bot.delete_messages = _noop_async
bot_utils_bot.get_webapp_url = lambda *a, **k: ""
sys.modules.setdefault("bot.utils.bot", bot_utils_bot)

bot_utils_chat = types.ModuleType("bot.utils.chat")
bot_utils_chat.send_coach_request = lambda *a, **k: None
sys.modules.setdefault("bot.utils.chat", bot_utils_chat)

bot_utils_profiles = types.ModuleType("bot.utils.profiles")
bot_utils_profiles.get_assigned_coach = lambda *a, **k: None
bot_utils_profiles.fetch_user = lambda *a, **k: None
bot_utils_profiles.answer_profile = lambda *a, **k: None
sys.modules.setdefault("bot.utils.profiles", bot_utils_profiles)

workout_models = types.ModuleType("apps.workout_plans.models")


class Program:
    pass


class Subscription:
    pass


workout_models.Program = Program
workout_models.Subscription = Subscription
sys.modules.setdefault("apps.workout_plans.models", workout_models)

core_services_pkg = types.ModuleType("core.services")
core_services_pkg.__path__ = [str(ROOT_DIR / "core" / "services")]
core_services_pkg.ProfileService = types.SimpleNamespace(
    get_client_by_profile_id=lambda *_a, **_k: None,
    get_client=lambda *_a, **_k: None,
)
core_services_pkg.APIService = types.SimpleNamespace(
    profile=types.SimpleNamespace(),
    payment=types.SimpleNamespace(),
    workout=types.SimpleNamespace(),
    ai_coach=types.SimpleNamespace(),
)


async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
    return None


core_services_pkg.APIService.workout.get_latest_program = _noop_async
core_services_pkg.get_gif_manager = lambda: types.SimpleNamespace(find_gif=lambda *a, **k: None)
core_services_pkg.get_avatar_manager = lambda: types.SimpleNamespace(bucket_name="")
sys.modules.setdefault("core.services", core_services_pkg)

env_defaults = {
    "API_KEY": "test_api_key",
    "API_URL": "http://localhost/",
    "BOT_TOKEN": "bot_token",
    "BOT_LINK": "http://bot",
    "WEBHOOK_HOST": "http://localhost",
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

# Ensure Django's method_decorator is a no-op to avoid requiring dispatch
from django.utils import decorators as _decorators  # noqa: E402

_decorators.method_decorator = lambda *a, **k: (lambda f: f)
