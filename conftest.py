import os
import sys
import types

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
}
modules["cognee.modules.data.exceptions"].DatasetNotFoundError = Exception
modules["cognee.modules.users.exceptions.exceptions"].PermissionDeniedError = Exception
modules["cognee.modules.users.methods.get_default_user"].get_default_user = lambda: None
modules["cognee.infrastructure.databases.exceptions"].DatabaseNotCreatedError = Exception
modules["cognee.modules.engine.operations.setup"].setup = lambda: None

for name, mod in modules.items():
    sys.modules.setdefault(name, mod)

# Stub heavy optional dependencies used by ai_coach
sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.oauth2", types.ModuleType("google.oauth2"))
service_account = types.ModuleType("google.oauth2.service_account")
service_account.Credentials = object
sys.modules.setdefault("google.oauth2.service_account", service_account)
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
)
sys.modules.setdefault("loguru", loguru_mod)
settings_stub = types.SimpleNamespace(
    VECTORDATABASE_URL="sqlite://",
    LOG_LEVEL="INFO",
    GDRIVE_FOLDER_ID="folder",
    GOOGLE_APPLICATION_CREDENTIALS="/tmp/creds.json",
    REDIS_URL="redis://localhost:6379",
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
sys.modules.setdefault("pydantic", pydantic_mod)
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
