"""Utilities for preparing Ask AI requests from user messages."""

from dataclasses import dataclass
from typing import Any
from base64 import b64encode

from aiogram import Bot
from aiogram.types import Message

from bot.utils.credits import available_ai_services
from bot.utils.media import download_limited_file, get_ai_qa_image_limit
from config.app_settings import settings
from core.cache import Cache
from core.exceptions import ClientNotFoundError
from core.schemas import Client, Profile


@dataclass(slots=True)
class AskAiPreparationResult:
    client: Client
    prompt: str
    cost: int
    image_base64: str | None
    image_mime: str | None


class AskAiPreparationError(Exception):
    def __init__(self, message_key: str, *, params: dict[str, Any] | None = None, delete_message: bool = True) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params or {}
        self.delete_message = delete_message


async def prepare_ask_ai_request(
    *,
    message: Message,
    profile: Profile,
    state_data: dict[str, Any],
    bot: Bot,
) -> AskAiPreparationResult:
    client_data = state_data.get("client")
    if client_data is None:
        try:
            client = await Cache.client.get_client(profile.id)
        except ClientNotFoundError as exc:
            raise AskAiPreparationError("unexpected_error") from exc
    else:
        client = Client.model_validate(client_data)

    prompt_raw = (message.text or message.caption or "").strip()
    if not prompt_raw:
        raise AskAiPreparationError("invalid_content")

    services = {service.name: service.credits for service in available_ai_services()}
    default_cost = int(settings.ASK_AI_PRICE)
    cost_hint = state_data.get("ask_ai_cost")
    cost = int(cost_hint or services.get("ask_ai", default_cost))

    if client.credits < cost:
        raise AskAiPreparationError("not_enough_credits")

    image_base64: str | None = None
    image_mime: str | None = None
    limit_bytes = get_ai_qa_image_limit()

    if message.photo:
        photo = message.photo[-1]
        file_bytes, size_hint = await download_limited_file(bot, photo.file_id)
        if file_bytes is None:
            if size_hint and size_hint > limit_bytes:
                raise AskAiPreparationError("image_error")
            raise AskAiPreparationError("unexpected_error")
        image_base64 = b64encode(file_bytes).decode("ascii")
        image_mime = "image/jpeg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        document = message.document
        file_bytes, size_hint = await download_limited_file(bot, document.file_id)
        if file_bytes is None:
            if size_hint and size_hint > limit_bytes:
                raise AskAiPreparationError("image_error")
            raise AskAiPreparationError("unexpected_error")
        image_base64 = b64encode(file_bytes).decode("ascii")
        image_mime = document.mime_type

    return AskAiPreparationResult(
        client=client,
        prompt=prompt_raw,
        cost=cost,
        image_base64=image_base64,
        image_mime=image_mime,
    )
