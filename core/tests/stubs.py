import os
import sys
import types
from pathlib import Path
from typing import Any, Mapping
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import url2pathname

# --- HIGH-PRIORITY STUBS ---

# Redis (asyncio)
redis_module = types.ModuleType("redis")
redis_asyncio = types.ModuleType("redis.asyncio")
redis_asyncio_client = types.ModuleType("redis.asyncio.client")
redis_exceptions = types.ModuleType("redis.exceptions")


class Redis:
    def __init__(self):
        self._kv = {}

    async def get(self, key):
        return self._kv.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._kv:
            return False
        self._kv[key] = value
        return True

    async def exists(self, key):
        return 1 if key in self._kv else 0

    async def expire(self, key, ttl):
        return True

    async def hget(self, key, field):
        bucket = self._kv.get(key)
        if isinstance(bucket, dict):
            return bucket.get(field)
        return None

    async def hset(self, key, field, value, nx=False):
        bucket = self._kv.setdefault(key, {})
        if nx and field in bucket:
            return 0
        bucket[field] = value
        return 1

    def pipeline(self):
        return Pipeline(self)

    async def execute(self):
        return True

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()


class Pipeline:
    def __init__(self, redis_instance=None):
        self._redis = redis_instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def watch(self, *args, **kwargs):
        return None

    async def multi(self, *args, **kwargs):
        return None

    async def pexpire(self, *args, **kwargs):
        return None

    async def execute(self):
        return []


class RedisError(Exception): ...


def from_url(*args, **kwargs):
    return Redis.from_url(*args, **kwargs)


redis_asyncio.Redis = Redis
redis_asyncio.from_url = from_url
redis_asyncio.Pipeline = Pipeline
redis_asyncio_client.Pipeline = Pipeline
redis_exceptions.RedisError = RedisError
redis_module.asyncio = redis_asyncio
sys.modules["redis"] = redis_module
sys.modules["redis.asyncio"] = redis_asyncio
sys.modules["redis.asyncio.client"] = redis_asyncio_client
sys.modules["redis.exceptions"] = redis_exceptions

# Cognee stubs
cognee_module = types.ModuleType("cognee")
infrastructure = types.ModuleType("cognee.infrastructure")
files_module = types.ModuleType("cognee.infrastructure.files")
utils_module = types.ModuleType("cognee.infrastructure.files.utils")


def open_file(path: str | os.PathLike[str]):
    raise FileNotFoundError(path)


utils_module.open_file = open_file
files_module.utils = utils_module
infrastructure.files = files_module
cognee_module.infrastructure = infrastructure

sys.modules["cognee"] = cognee_module
sys.modules["cognee.infrastructure"] = infrastructure
sys.modules["cognee.infrastructure.files"] = files_module
sys.modules["cognee.infrastructure.files.utils"] = utils_module

base_config_module = types.ModuleType("cognee.base_config")


def get_base_config() -> SimpleNamespace:
    return SimpleNamespace(data_root_directory=".")


base_config_module.get_base_config = get_base_config
sys.modules["cognee.base_config"] = base_config_module


class _AsyncFile:
    def __init__(self, path: Path, mode: str) -> None:
        self._path = path
        self._mode = mode
        self._file = open(path, mode)

    async def __aenter__(self):
        return self._file

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._file.close()


def open_data_file(uri: str | os.PathLike[str], mode: str = "r"):
    root = Path(base_config_module.get_base_config().data_root_directory or ".")
    parsed = urlparse(str(uri))

    path_str = ""
    if parsed.path:
        path_str = url2pathname(parsed.path)
    elif parsed.netloc:  # Handle file://C:\... case
        path_str = url2pathname(parsed.netloc)

    # Handle Windows paths like /C:/... on non-Windows systems
    if len(path_str) > 2 and path_str[0] == "/" and path_str[2] == ":":
        path_str = path_str[1:]

    if "\\" in path_str:
        filename = os.path.basename(path_str.replace("\\", "/"))
    else:
        filename = Path(path_str).name

    if not filename:  # This can happen if path_str is empty or just '/'
        raise ValueError(f"Could not determine filename from URI: {uri}")

    target = root / filename
    return _AsyncFile(target, mode)


utils_module.open_data_file = open_data_file

# aiogram
aiogram = types.ModuleType("aiogram")
aiogram.__path__ = []
sys.modules["aiogram"] = aiogram

aiogram.utils = types.ModuleType("aiogram.utils")
sys.modules["aiogram.utils"] = aiogram.utils
aiogram.utils.keyboard = types.ModuleType("aiogram.utils.keyboard")
sys.modules["aiogram.utils.keyboard"] = aiogram.utils.keyboard


class InlineKeyboardBuilder: ...


aiogram.utils.keyboard.InlineKeyboardBuilder = InlineKeyboardBuilder


aiogram.types = types.ModuleType("aiogram.types")
aiogram.types.__path__ = []
sys.modules["aiogram.types"] = aiogram.types

aiogram.fsm = types.ModuleType("aiogram.fsm")
aiogram.fsm.__path__ = []
sys.modules["aiogram.fsm"] = aiogram.fsm

aiogram.fsm.state = types.ModuleType("aiogram.fsm.state")
sys.modules["aiogram.fsm.state"] = aiogram.fsm.state


class State:
    def __init__(self, state: str = "") -> None:
        self.state = state


class StatesGroup: ...


aiogram.fsm.state.State = State
aiogram.fsm.state.StatesGroup = StatesGroup


aiogram.fsm.storage = types.ModuleType("aiogram.fsm.storage")
aiogram.fsm.storage.__path__ = []
sys.modules["aiogram.fsm.storage"] = aiogram.fsm.storage

aiogram.fsm.storage.base = types.ModuleType("aiogram.fsm.storage.base")
sys.modules["aiogram.fsm.storage.base"] = aiogram.fsm.storage.base

aiogram.fsm.storage.memory = types.ModuleType("aiogram.fsm.storage.memory")
sys.modules["aiogram.fsm.storage.memory"] = aiogram.fsm.storage.memory

aiogram.fsm.context = types.ModuleType("aiogram.fsm.context")
sys.modules["aiogram.fsm.context"] = aiogram.fsm.context

aiogram.client = types.ModuleType("aiogram.client")
sys.modules["aiogram.client"] = aiogram.client
aiogram.client.default = types.ModuleType("aiogram.client.default")
sys.modules["aiogram.client.default"] = aiogram.client.default

aiogram.exceptions = types.ModuleType("aiogram.exceptions")
sys.modules["aiogram.exceptions"] = aiogram.exceptions

aiogram.enums = types.ModuleType("aiogram.enums")
sys.modules["aiogram.enums"] = aiogram.enums


class Bot: ...


aiogram.Bot = Bot


class FSMContext:
    def __init__(self, *, storage: "MemoryStorage", key: "StorageKey"):
        self._storage = storage
        self._key = key

    async def get_state(self) -> Any:
        return await self._storage.get_state(self._key)

    async def set_state(self, state: Any) -> Any:
        await self._storage.set_state(self._key, state)
        return state

    async def get_data(self) -> dict[str, Any]:
        return await self._storage.get_data(self._key)

    async def set_data(self, data: dict[str, Any]) -> dict[str, Any]:
        await self._storage.set_data(self._key, data)
        return data

    async def update_data(self, **kwargs: Any) -> dict[str, Any]:
        return await self._storage.update_data(self._key, **kwargs)

    async def clear(self) -> None:
        await self._storage.clear_state(self._key)
        await self._storage.clear_data(self._key)


aiogram.fsm.context.FSMContext = FSMContext


class DefaultBotProperties: ...


aiogram.client.default.DefaultBotProperties = DefaultBotProperties


class TelegramBadRequest: ...


aiogram.exceptions.TelegramBadRequest = TelegramBadRequest


class ParseMode: ...


aiogram.enums.ParseMode = ParseMode


class MemoryStorage:
    def __init__(self) -> None:
        self._state: dict[tuple[Any, Any, Any], Any] = {}
        self._data: dict[tuple[Any, Any, Any], dict[str, Any]] = {}

    @staticmethod
    def _key_tuple(key: Any) -> tuple[Any, Any, Any]:
        return (getattr(key, "bot_id", None), getattr(key, "chat_id", None), getattr(key, "user_id", None))

    async def set_state(self, key: Any, state: Any) -> None:
        self._state[self._key_tuple(key)] = state

    async def get_state(self, key: Any) -> Any:
        return self._state.get(self._key_tuple(key))

    async def clear_state(self, key: Any) -> None:
        self._state.pop(self._key_tuple(key), None)

    async def set_data(self, key: Any, data: dict[str, Any]) -> None:
        self._data[self._key_tuple(key)] = dict(data)

    async def get_data(self, key: Any) -> dict[str, Any]:
        stored = self._data.get(self._key_tuple(key))
        return dict(stored) if stored is not None else {}

    async def update_data(self, key: Any, data: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        storage_key = self._key_tuple(key)
        current = self._data.setdefault(storage_key, {})
        updates = dict(data or {})
        updates.update(kwargs)
        current.update(updates)
        return dict(current)

    async def clear_data(self, key: Any) -> None:
        self._data.pop(self._key_tuple(key), None)

    async def close(self) -> None:
        self._state.clear()
        self._data.clear()


aiogram.fsm.storage.memory.MemoryStorage = MemoryStorage


class SwitchInlineQueryChosenChat:
    def __init__(
        self,
        query: str | None = None,
        allow_user_chats: bool = False,
        allow_bot_chats: bool = False,
        allow_group_chats: bool = False,
        allow_channel_chats: bool = False,
    ):
        self.query = query
        self.allow_user_chats = allow_user_chats
        self.allow_bot_chats = allow_bot_chats
        self.allow_group_chats = allow_group_chats
        self.allow_channel_chats = allow_channel_chats


class Message: ...


class InputSticker: ...


class InputFile: ...


class ResponseParameters: ...


class UNSET_TYPE: ...


class CallbackQuery: ...


class BotCommand: ...


class FSInputFile: ...


class InlineKeyboardButton: ...


class InlineKeyboardMarkup: ...


class WebAppInfo: ...


aiogram.types.SwitchInlineQueryChosenChat = SwitchInlineQueryChosenChat
aiogram.types.Message = Message
aiogram.types.InputSticker = InputSticker
aiogram.types.InputFile = InputFile
aiogram.types.ResponseParameters = ResponseParameters
aiogram.types.CallbackQuery = CallbackQuery
aiogram.types.BotCommand = BotCommand
aiogram.types.FSInputFile = FSInputFile
aiogram.types.InlineKeyboardButton = InlineKeyboardButton
aiogram.types.InlineKeyboardMarkup = InlineKeyboardMarkup
aiogram.types.WebAppInfo = WebAppInfo


aiogram.types.base = types.ModuleType("aiogram.types.base")
sys.modules["aiogram.types.base"] = aiogram.types.base
aiogram.types.base.UNSET_TYPE = UNSET_TYPE


class StorageKey:
    def __init__(self, bot_id, chat_id=None, user_id=None, state=None):
        self.bot_id = bot_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.state = state


aiogram.fsm.storage.base.StorageKey = StorageKey


# cryptography.fernet
if "cryptography" not in sys.modules:
    sys.modules["cryptography"] = types.ModuleType("cryptography")
if "cryptography.fernet" not in sys.modules:
    fernet = types.ModuleType("cryptography.fernet")

    class Fernet:
        def __init__(self, key):
            pass

        def encrypt(self, data):
            return data

        def decrypt(self, token):
            return token

    fernet.Fernet = Fernet
    sys.modules["cryptography.fernet"] = fernet

# loguru logger
if "loguru" not in sys.modules:
    loguru = types.ModuleType("loguru")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

        def remove(self, *args, **kwargs):
            return None

        def add(self, *args, **kwargs):
            return 0

        def bind(self, *args, **kwargs):
            return self

        def catch(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def opt(self, *args, **kwargs):
            return self

        def contextualize(self, **kwargs):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return _Ctx()

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    loguru.logger = _Logger()
    sys.modules["loguru"] = loguru

# pydantic_ai and friends
if "pydantic_ai" not in sys.modules:
    pydantic_ai = types.ModuleType("pydantic_ai")

    class Agent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self._system_prompt = None
            self._instructions = None

        def system_prompt(self, func=None):
            def decorator(fn):
                self._system_prompt = fn
                return fn

            return decorator(func) if func is not None else decorator

        def instructions(self, func=None):
            def decorator(fn):
                self._instructions = fn
                return fn

            return decorator(func) if func is not None else decorator

        async def run(self, *args, **kwargs):
            return {}

    class RunContext:
        def __class_getitem__(cls, item):
            return cls

    class ModelRetry(Exception): ...

    pydantic_ai.Agent = Agent
    pydantic_ai.RunContext = RunContext
    pydantic_ai.ModelRetry = ModelRetry
    sys.modules["pydantic_ai"] = pydantic_ai

    pydantic_ai.tools = types.ModuleType("pydantic_ai.tools")

    class ToolDefinition: ...

    pydantic_ai.tools.ToolDefinition = ToolDefinition
    sys.modules["pydantic_ai.tools"] = pydantic_ai.tools

    pydantic_ai.toolsets = types.ModuleType("pydantic_ai.toolsets")
    pydantic_ai.toolsets.function = types.ModuleType("pydantic_ai.toolsets.function")

    class FunctionToolset:
        def __init__(self, *args, **kwargs): ...
        def add_function(self, *args, **kwargs): ...
        def tool(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    pydantic_ai.toolsets.function.FunctionToolset = FunctionToolset
    sys.modules["pydantic_ai.toolsets"] = pydantic_ai.toolsets
    sys.modules["pydantic_ai.toolsets.function"] = pydantic_ai.toolsets.function

    pydantic_ai.messages = types.ModuleType("pydantic_ai.messages")

    class ModelMessage:
        pass

    class ModelRequest:
        @staticmethod
        def user_text_prompt(text: str):
            return {"role": "user", "text": text}

    class ModelResponse:
        def __init__(self, parts=None):
            self.parts = parts or []

    class TextPart:
        def __init__(self, content: str = ""):
            self.content = content

    pydantic_ai.messages.ModelMessage = ModelMessage
    pydantic_ai.messages.ModelRequest = ModelRequest
    pydantic_ai.messages.ModelResponse = ModelResponse
    pydantic_ai.messages.TextPart = TextPart
    sys.modules["pydantic_ai.messages"] = pydantic_ai.messages

    pydantic_ai.models = types.ModuleType("pydantic_ai.models")
    pydantic_ai.models.openai = types.ModuleType("pydantic_ai.models.openai")

    class OpenAIChatModel:
        def __init__(self, *args, **kwargs):
            self.client = None

    pydantic_ai.models.openai.OpenAIChatModel = OpenAIChatModel
    sys.modules["pydantic_ai.models"] = pydantic_ai.models
    sys.modules["pydantic_ai.models.openai"] = pydantic_ai.models.openai

    pydantic_ai.settings = types.ModuleType("pydantic_ai.settings")

    class ModelSettings:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    pydantic_ai.settings.ModelSettings = ModelSettings
    sys.modules["pydantic_ai.settings"] = pydantic_ai.settings

    pydantic_ai.providers = types.ModuleType("pydantic_ai.providers")
    pydantic_ai.providers.openrouter = types.ModuleType("pydantic_ai.providers.openrouter")

    class OpenRouterProvider:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    pydantic_ai.providers.openrouter.OpenRouterProvider = OpenRouterProvider
    sys.modules["pydantic_ai.providers"] = pydantic_ai.providers
    sys.modules["pydantic_ai.providers.openrouter"] = pydantic_ai.providers.openrouter


# Celery
celery = types.ModuleType("celery")


class Celery:
    def __init__(self, *args, **kwargs):
        self.tasks = {}
        self.conf = {}

    def task(self, *args, **kwargs):
        class _Signature:
            def __init__(self, func, bound_args, bound_kwargs):
                self._func = func
                self._args = tuple(bound_args)
                self._kwargs = dict(bound_kwargs)
                self._options: dict[str, Any] = {}

            def set(self, **options):
                self._options.update(options)
                return self

            def apply_async(self, *args, **kwargs):
                call_args = self._args + tuple(kwargs.get("args") or ())
                call_kwargs = dict(self._kwargs)
                call_kwargs.update(kwargs.get("kwargs") or {})
                return self._func(*call_args, **call_kwargs)

        class _TaskWrapper:
            def __init__(self, func):
                self._func = func
                self.request = types.SimpleNamespace(retries=0)
                self.max_retries = 0

            def __call__(self, *call_args, **call_kwargs):
                return self._func(self, *call_args, **call_kwargs)

            def apply_async(self, args=None, kwargs=None, **options):
                call_args = tuple(args or ())
                call_kwargs = dict(kwargs or {})
                return self._func(self, *call_args, **call_kwargs)

            def delay(self, *call_args, **call_kwargs):
                return self._func(self, *call_args, **call_kwargs)

            def s(self, *call_args, **call_kwargs):
                return _Signature(self._func, call_args, call_kwargs)

            def set(self, **options):
                return self

            def retry(self, *args, **kwargs):
                raise RuntimeError("retry invoked in stub task")

            def run(self, *call_args, **call_kwargs):
                return self._func(self, *call_args, **call_kwargs)

        def decorator(func):
            wrapped = _TaskWrapper(func)
            task_name = f"{func.__module__}.{func.__name__}"
            self.tasks[task_name] = wrapped
            self.tasks[func.__name__] = wrapped
            return wrapped

        return decorator

    def autodiscover_tasks(self, *args, **kwargs):
        return None


class Task: ...


class _Sig:
    def connect(self, *args, **kwargs):
        return None


signals = types.SimpleNamespace(
    task_prerun=_Sig(),
    task_postrun=_Sig(),
    task_failure=_Sig(),
    task_success=_Sig(),
    worker_ready=_Sig(),
    after_setup_task_logger=_Sig(),
)


def chain(*tasks):
    class _Result:
        def apply_async(self, *args, **kwargs):
            return types.SimpleNamespace(id="task-id")

    return _Result()


celery.Celery = Celery
celery.Task = Task
celery.signals = signals
celery.chain = chain

celery_result = types.ModuleType("celery.result")


class AsyncResult:
    def __init__(self, task_id="task-id"):
        self.id = task_id


celery_result.AsyncResult = AsyncResult
sys.modules["celery"] = celery
sys.modules["celery.result"] = celery_result

celery_apps = types.ModuleType("celery.apps")
celery_worker = types.ModuleType("celery.apps.worker")


class WorkController: ...


celery_worker.WorkController = WorkController
sys.modules["celery.apps"] = celery_apps
sys.modules["celery.apps.worker"] = celery_worker

celery_schedules = types.ModuleType("celery.schedules")


class crontab:
    def __init__(self, *args, **kwargs): ...


class schedule:
    def __init__(self, *args, **kwargs): ...


celery_schedules.crontab = crontab
celery_schedules.schedule = schedule
sys.modules["celery.schedules"] = celery_schedules
