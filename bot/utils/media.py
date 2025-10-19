"""Helpers for working with Telegram media within bot flows."""

import io

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from config.app_settings import settings


def get_ai_qa_image_limit() -> int:
    return int(settings.AI_QA_IMAGE_MAX_BYTES)


async def download_limited_file(
    bot: Bot, file_id: str, *, max_bytes: int | None = None
) -> tuple[bytes | None, int | None]:
    """Download a Telegram file if it fits within the configured byte limit."""

    limit = max_bytes or get_ai_qa_image_limit()
    try:
        file = await bot.get_file(file_id)
    except TelegramBadRequest as exc:
        logger.warning(f"event=ask_ai_get_file_failed file_id={file_id} error={exc}")
        return None, None

    size_hint = getattr(file, "file_size", None)
    if size_hint and size_hint > limit:
        logger.info(
            "event=ask_ai_attachment_rejected reason=size_hint file_id={} size={} limit={}",
            file_id,
            size_hint,
            limit,
        )
        return None, size_hint

    buffer = io.BytesIO()
    try:
        await bot.download_file(file.file_path, buffer)
    except TelegramBadRequest as exc:
        logger.warning(f"event=ask_ai_download_failed file_id={file_id} error={exc}")
        return None, size_hint

    data = buffer.getvalue()
    if len(data) > limit:
        logger.info(
            "event=ask_ai_attachment_rejected reason=download_size file_id={} size={} limit={}",
            file_id,
            len(data),
            limit,
        )
        return None, len(data)

    return data, size_hint or len(data)
