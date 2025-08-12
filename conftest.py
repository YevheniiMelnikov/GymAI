# pyrefly: ignore-file
# pyright: reportGeneralTypeIssues=false
import os
import sys
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

os.environ["TIME_ZONE"] = "Europe/Kyiv"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")

# Provide minimal stub for the external 'cognee' package
cognee_stub = types.ModuleType("cognee")
cognee_stub.__path__ = []  # mark as package so submodules can be imported
cognee_stub.add = lambda *a, **k: None
cognee_stub.cognify = lambda *a, **k: None
cognee_stub.search = lambda *a, **k: []
cognee_stub.config = types.SimpleNamespace(
    set_llm_provider=lambda *a, **k: None,
    set_llm_model=lambda *a, **k: None,
    set_llm_api_key=lambda *a, **k: None,
    set_llm_endpoint=lambda *a, **k: None,
    set_vector_db_provider=lambda *a, **k: None,
    set_vector_db_url=lambda *a, **k: None,
    data_root_directory=lambda *a, **k: None,
    set_graph_database_provider=lambda *a, **k: None,
    set_relational_db_config=lambda *a, **k: None,
)

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

# Minimal FastAPI stubs
fastapi_mod = types.ModuleType("fastapi")


class _FastAPI:
    def __init__(self, *a, **k):
        pass


fastapi_mod.FastAPI = _FastAPI
fastapi_security = types.ModuleType("fastapi.security")
fastapi_security.HTTPBasic = object
sys.modules.setdefault("fastapi", fastapi_mod)
sys.modules.setdefault("fastapi.security", fastapi_security)

# Minimal httpx stub for API client tests
httpx_mod = types.ModuleType("httpx")


class _Request:
    def __init__(self, method: str, url: str):
        self.method = method
        self.url = url


class _Response:
    pass


class _HTTPError(Exception):
    pass


class _HTTPStatusError(_HTTPError):
    def __init__(self, message: str, request: _Request, response: _Response):
        super().__init__(message)
        self.request = request
        self.response = response


class _DecodingError(Exception):
    pass


httpx_mod.Request = _Request
httpx_mod.Response = _Response
httpx_mod.HTTPStatusError = _HTTPStatusError
httpx_mod.DecodingError = _DecodingError
httpx_mod.HTTPError = _HTTPError
class _AsyncClient:
    async def request(self, *a, **k):
        return _Response()


httpx_mod.AsyncClient = _AsyncClient
sys.modules.setdefault("httpx", httpx_mod)


class _DummyProfileService:
    async def get_client_by_profile_id(self, profile_id):
        return None


class _DummyWorkoutService:
    async def get_latest_subscription(self, client_profile_id):
        return None

    async def get_latest_program(self, client_profile_id):
        return None

services_mod = types.ModuleType("core.services")
services_mod.__path__ = [str(Path(__file__).resolve().parent / "core" / "services")]
services_mod.ProfileService = _DummyProfileService
services_mod.WorkoutService = _DummyWorkoutService
sys.modules.setdefault("core.services", services_mod)
import core as _core_pkg  # noqa: E402
_core_pkg.services = services_mod

schemas_mod = types.ModuleType("core.schemas")


@dataclass
class Exercise:
    name: str
    sets: str
    reps: str
    gif_link: str | None = None
    weight: str | None = None
    set_id: int | None = None
    drop_set: bool = False


@dataclass
class DayExercises:
    day: str
    exercises: list[Exercise] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {"day": self.day, "exercises": [e.__dict__ for e in self.exercises]}


@dataclass
class Client:
    id: int
    profile: int
    name: str | None = None
    gender: str | None = None
    born_in: str | None = None
    workout_experience: str | None = None
    workout_goals: str | None = None
    profile_photo: str | None = None
    health_notes: str | None = None
    weight: int | None = None
    status: str | None = None
    assigned_to: list[int] = field(default_factory=list)
    credits: int = 0
    profile_data: dict[str, Any] = field(default_factory=dict)


schemas_mod.Exercise = Exercise
schemas_mod.DayExercises = DayExercises
schemas_mod.Client = Client
@dataclass
class Profile:
    id: int


@dataclass
class Subscription:
    workout_days: list[str] = field(default_factory=list)
    exercises: list[DayExercises] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "workout_days": self.workout_days,
            "exercises": [de.model_dump() for de in self.exercises],
        }


@dataclass
class Program:
    client_profile: int = 0
    exercises_by_day: list[DayExercises] = field(default_factory=list)
    workout_days: list[str] = field(default_factory=list)
    id: int = 0

    def model_dump(self) -> dict[str, Any]:
        return {
            "client_profile": self.client_profile,
            "exercises_by_day": [de.model_dump() for de in self.exercises_by_day],
            "workout_days": self.workout_days,
            "id": self.id,
        }


schemas_mod.Profile = Profile
schemas_mod.Subscription = Subscription
schemas_mod.Program = Program
sys.modules.setdefault("core.schemas", schemas_mod)
_core_pkg.schemas = schemas_mod
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
    success=lambda *a, **k: None,
    exception=lambda *a, **k: None,
    level=lambda *a, **k: None,
)
sys.modules.setdefault("loguru", loguru_mod)
settings_stub = types.SimpleNamespace(
    VECTORDATABASE_URL="sqlite://",
    VECTORDATABASE_PROVIDER="sqlite",
    GRAPH_DATABASE_PROVIDER="sqlite",
    DB_HOST="localhost",
    DB_PORT=5432,
    DB_USER="user",
    DB_PASSWORD="pass",
    DB_NAME="db",
    DB_PROVIDER="sqlite",
    LOG_LEVEL="INFO",
    GDRIVE_FOLDER_ID="folder",
    GOOGLE_APPLICATION_CREDENTIALS="/tmp/creds.json",
    SPREADSHEET_ID="sheet",
    REDIS_URL="redis://localhost:6379",
    API_URL="http://localhost/",
    API_KEY="test_api_key",
    API_MAX_RETRIES=2,
    API_RETRY_INITIAL_DELAY=0,
    API_RETRY_BACKOFF_FACTOR=1,
    API_RETRY_MAX_DELAY=0,
    API_TIMEOUT=1,
    LLM_PROVIDER="openai",
    LLM_MODEL="gpt-3.5",
    LLM_API_KEY="key",
    LLM_API_URL="http://llm",
    EMBEDDING_MODEL="embed",
    EMBEDDING_API_KEY="embed_key",
    OPENAI_BASE_URL="http://openai",
)
sys.modules.setdefault("config.app_settings", types.ModuleType("config.app_settings"))
sys.modules["config.app_settings"].settings = settings_stub
logger_stub = types.ModuleType("config.logger")
logger_stub.configure_loguru = lambda: None
logger_stub.LOGGING = {}
sys.modules.setdefault("config.logger", logger_stub)
crypto_mod = types.ModuleType("cryptography")
crypto_mod.fernet = types.ModuleType("cryptography.fernet")


class _DummyFernet:
    def __init__(self, key: bytes):
        self.key = key

    def encrypt(self, data: bytes) -> bytes:
        return data[::-1]

    def decrypt(self, token: bytes) -> bytes:
        return token[::-1]


crypto_mod.fernet.Fernet = _DummyFernet
sys.modules.setdefault("cryptography", crypto_mod)
sys.modules.setdefault("cryptography.fernet", crypto_mod.fernet)
sqlalchemy_mod = types.ModuleType("sqlalchemy")
sqlalchemy_mod.schema = types.ModuleType("sqlalchemy.schema")
sqlalchemy_mod.exc = types.ModuleType("sqlalchemy.exc")
sqlalchemy_mod.exc.SAWarning = type("SAWarning", (Warning,), {})
sys.modules.setdefault("sqlalchemy", sqlalchemy_mod)
sys.modules.setdefault("sqlalchemy.schema", sqlalchemy_mod.schema)
sys.modules.setdefault("sqlalchemy.exc", sqlalchemy_mod.exc)

# provide Redis stub before importing ai_coach modules
redis_async_mod = types.ModuleType("redis.asyncio")


class DummyRedis:
    async def sadd(self, *a, **k):
        pass

    async def sismember(self, *a, **k):
        return False


redis_async_mod.Redis = type("Redis", (), {"from_url": lambda *a, **k: DummyRedis()})
sys.modules.setdefault("redis.asyncio", redis_async_mod)
redis_ex_mod = types.ModuleType("redis.exceptions")
redis_ex_mod.RedisError = Exception
sys.modules.setdefault("redis.exceptions", redis_ex_mod)

# minimal Django settings module for payment service
django_mod = types.ModuleType("django")
django_conf = types.ModuleType("django.conf")
django_conf.settings = types.SimpleNamespace(
    PAYMENT_CALLBACK_URL="",
    BOT_LINK="",
    EMAIL="",
    CHECKOUT_URL="",
)
django_mod.conf = django_conf
sys.modules.setdefault("django", django_mod)
sys.modules.setdefault("django.conf", django_conf)
django_db_mod = types.ModuleType("django.db")
django_db_models = types.ModuleType("django.db.models")
django_db_models.QuerySet = list
django_db_mod.models = django_db_models
sys.modules.setdefault("django.db", django_db_mod)
sys.modules.setdefault("django.db.models", django_db_models)
cache_store: dict = {}
django_core_cache = types.ModuleType("django.core.cache")
django_core_cache.cache = types.SimpleNamespace(
    get=lambda k, default=None: cache_store.get(k, default),
    set=lambda k, v: cache_store.__setitem__(k, v),
    get_or_set=lambda k, func, timeout=None: cache_store.setdefault(k, func()),
    delete=lambda k: cache_store.pop(k, None),
    delete_many=lambda keys: [cache_store.pop(k, None) for k in keys],
)
sys.modules.setdefault("django.core", types.ModuleType("django.core"))
sys.modules.setdefault("django.core.cache", django_core_cache)
django_test_mod = types.ModuleType("django.test")
sys.modules.setdefault("django.test", django_test_mod)

# provide missing hook for ai_coach tests
from ai_coach.cognee_coach import CogneeCoach  # noqa: E402


async def _ensure_config() -> None:
    return None


CogneeCoach._ensure_config = staticmethod(_ensure_config)


async def _get_client_context(cls, client_id: int, query: str) -> dict[str, list[str]]:
    user = await cls._get_cognee_user()
    cls._ensure_profile_indexed(client_id, user)
    datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
    try:
        messages = await cognee_stub.search(query, datasets=datasets, top_k=5, user=user)
    except Exception:  # pragma: no cover
        messages = []
    return {"messages": messages}


async def _update_dataset(text: str, dataset: str, user: Any, node_set: list[str] | None = None):
    info = await cognee_stub.add(text, dataset_name=dataset, user=user)
    ds = getattr(info, "dataset_id", dataset)
    return ds, True


CogneeCoach.get_client_context = classmethod(_get_client_context)
CogneeCoach.update_dataset = staticmethod(_update_dataset)


async def _make_request(cls, prompt: str, client_id: int) -> list[str]:
    user = await cls._get_cognee_user()
    cls._ensure_profile_indexed(client_id, user)
    try:
        return await cognee_stub.search(prompt, datasets=[cls._dataset_name(client_id), cls.GLOBAL_DATASET], user=user)
    except Exception:  # pragma: no cover
        return []


CogneeCoach.make_request = classmethod(_make_request)

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

# initialize services after stubs are in place
from core.services.payments.liqpay import LiqPay, LiqPayGateway, ParamValidationError  # noqa: E402

services_mod.LiqPayGateway = LiqPayGateway
services_mod.ParamValidationError = ParamValidationError


class _InMemoryManager(list):
    def create(self, **kwargs):
        obj = types.SimpleNamespace(**kwargs)
        obj.id = len(self) + 1
        self.append(obj)
        return obj

    def all(self):
        return list(self)


# Stub profile models
profiles_mod = types.ModuleType("apps.profiles.models")
class Profile(types.SimpleNamespace):
    objects = _InMemoryManager()


class ClientProfile(types.SimpleNamespace):
    objects = _InMemoryManager()


profiles_mod.Profile = Profile
profiles_mod.ClientProfile = ClientProfile
sys.modules.setdefault("apps.profiles.models", profiles_mod)


# Stub payment model
payments_models = types.ModuleType("apps.payments.models")
class Payment(types.SimpleNamespace):
    objects = _InMemoryManager()


payments_models.Payment = Payment
sys.modules.setdefault("apps.payments.models", payments_models)


# Minimal APIKey stub
api_models = types.ModuleType("rest_framework_api_key.models")


class _APIKeyManager:
    def create_key(self, name: str):
        return types.SimpleNamespace(name=name), "testkey"


class APIKey:
    objects = _APIKeyManager()


api_models.APIKey = APIKey
sys.modules.setdefault("rest_framework_api_key.models", api_models)


# Stub workout plan models used by repositories
workout_models = types.ModuleType("apps.workout_plans.models")


class Program(types.SimpleNamespace):
    objects = _InMemoryManager()


class Subscription(types.SimpleNamespace):
    objects = _InMemoryManager()


workout_models.Program = Program
workout_models.Subscription = Subscription
sys.modules.setdefault("apps.workout_plans.models", workout_models)


# Lightweight bot helpers to avoid aiogram dependency during tests
bot_utils_mod = types.ModuleType("bot.utils.bot")


async def _noop(*args, **kwargs):
    return None


bot_utils_mod.del_msg = _noop
bot_utils_mod.answer_msg = _noop
bot_utils_mod.delete_messages = _noop
sys.modules.setdefault("bot.utils.bot", bot_utils_mod)


keyboards_mod = types.ModuleType("bot.keyboards")
keyboards_mod.program_edit_kb = lambda *a, **k: None
keyboards_mod.program_manage_kb = lambda *a, **k: None
sys.modules.setdefault("bot.keyboards", keyboards_mod)


text_utils_mod = types.ModuleType("bot.utils.text")
text_utils_mod.get_translated_week_day = lambda lang, day: day
sys.modules.setdefault("bot.utils.text", text_utils_mod)


states_mod = types.ModuleType("bot.states")


class States:
    program_manage = object()
    program_edit = object()


states_mod.States = States
sys.modules.setdefault("bot.states", states_mod)


texts_pkg = types.ModuleType("bot.texts")
texts_pkg.__path__ = []
text_manager_mod = types.ModuleType("bot.texts.text_manager")
text_manager_mod.msg_text = lambda *a, **k: ""
texts_pkg.text_manager = text_manager_mod
sys.modules.setdefault("bot.texts", texts_pkg)
sys.modules.setdefault("bot.texts.text_manager", text_manager_mod)


# Stub views relying on in-memory models
class Response(dict):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.data = data
        self.status_code = status


class APIView:
    permission_classes = []

    @classmethod
    def as_view(cls):
        def view(request, *args, **kwargs):
            self = cls()
            handler = getattr(self, request.method.lower())
            return handler(request, *args, **kwargs)

        return view


class AllowAny:
    pass


class HttpRequest(types.SimpleNamespace):
    pass


def JsonResponse(data, status=200):
    return types.SimpleNamespace(status_code=status, data=data)


class APIRequestFactory:
    def get(self, path, data=None, **extra):
        return HttpRequest(method="GET", GET=data or {}, POST={}, **extra)

    def post(self, path, data=None, **extra):
        return HttpRequest(method="POST", POST=data or {}, GET={}, **extra)


rf_test_mod = types.ModuleType("rest_framework.test")
rf_test_mod.APIRequestFactory = APIRequestFactory
sys.modules.setdefault("rest_framework.test", rf_test_mod)
sys.modules.setdefault("rest_framework.views", types.ModuleType("rest_framework.views"))
sys.modules.setdefault("rest_framework.response", types.ModuleType("rest_framework.response"))
sys.modules.setdefault("rest_framework.permissions", types.ModuleType("rest_framework.permissions"))
sys.modules.setdefault("rest_framework.exceptions", types.ModuleType("rest_framework.exceptions"))

sys.modules["rest_framework.views"].APIView = APIView
sys.modules["rest_framework.response"].Response = Response
sys.modules["rest_framework.permissions"].AllowAny = AllowAny
sys.modules["rest_framework.exceptions"].NotFound = type("NotFound", (Exception,), {})
django_test_mod.RequestFactory = APIRequestFactory

import json  # noqa: E402
import base64  # noqa: E402

proc_mod = types.ModuleType("apps.payments.views.process_payment_webhook")
proc_mod.delay = lambda **kwargs: None


class PaymentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: HttpRequest, *args, **kwargs):
        status = request.GET.get("status")
        items = [
            {"order_id": p.order_id, "status": p.status}
            for p in Payment.objects.all()
            if not status or p.status == status
        ]
        return Response({"results": items})


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _verify_signature(raw_data: str, signature: str) -> bool:  # pragma: no cover - monkeypatched in tests
        lp = LiqPay("", "")
        expected = lp.str_to_sign(f"{raw_data}")
        return signature == expected

    @staticmethod
    def post(request: HttpRequest, *args, **kwargs) -> JsonResponse:
        raw_data = request.POST.get("data")
        signature = request.POST.get("signature")
        if not raw_data or not signature:
            return JsonResponse({"detail": "Missing fields"}, status=400)
        if not PaymentWebhookView._verify_signature(raw_data, signature):
            return JsonResponse({"detail": "Invalid signature"}, status=400)
        decoded = base64.b64decode(raw_data).decode()
        payload = json.loads(decoded)
        proc_mod.delay(
            order_id=payload.get("order_id"),
            status=payload.get("status"),
            err_description=payload.get("err_description", ""),
        )
        return JsonResponse({"result": "OK"})


payments_views = types.ModuleType("apps.payments.views")
payments_views.PaymentListView = PaymentListView
payments_views.PaymentWebhookView = PaymentWebhookView
payments_views.process_payment_webhook = proc_mod
sys.modules.setdefault("apps.payments.views.process_payment_webhook", proc_mod)
sys.modules.setdefault("apps.payments.views", payments_views)
import importlib  # noqa: E402
payments_pkg = importlib.import_module("apps.payments")
payments_pkg.views = payments_views
