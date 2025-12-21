import html
from typing import Any

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from bot.handlers.internal.schemas import AiAnswerBlock


def reply_target_missing(exc: TelegramBadRequest) -> bool:
    text = str(getattr(exc, "message", "") or "")
    if not text and exc.args:
        first_arg = exc.args[0]
        if isinstance(first_arg, str):
            text = first_arg
    lowered = text.lower()
    return (
        "reply message not found" in lowered
        or "message to reply not found" in lowered
        or "replied message not found" in lowered
    )


def extract_error_text(exc: TelegramBadRequest) -> str:
    text = str(getattr(exc, "message", "") or "")
    if not text and exc.args:
        for arg in exc.args:
            if isinstance(arg, str):
                text = arg
                break
    return text


async def send_chunk_with_reply_fallback(
    *,
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: ParseMode,
    reply_markup: Any | None,
    reply_to_message_id: int | None,
) -> int | None:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return reply_to_message_id
    except TelegramBadRequest as exc:
        if reply_to_message_id is not None:
            error_text = extract_error_text(exc)
            if reply_target_missing(exc):
                logger.warning(
                    "event=ask_ai_reply_target_missing chat_id={} detail={}",
                    chat_id,
                    error_text,
                )
            else:
                logger.warning(
                    "event=ask_ai_reply_send_failed chat_id={} detail={}",
                    chat_id,
                    error_text,
                )
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_to_message_id=None,
                reply_markup=reply_markup,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "event=ask_ai_reply_unexpected_failure chat_id={} reply_to={} error={}",
            chat_id,
            reply_to_message_id,
            exc,
        )
        raise


def format_answer_blocks(blocks: list[AiAnswerBlock]) -> str:
    lines: list[str] = []
    for block in blocks:
        title = (block.title or "").strip()
        body = (block.body or "").strip()
        if not body:
            continue
        if title:
            lines.append(f"<b>{html.escape(title, quote=False)}</b>")
        lines.append(html.escape(body, quote=False).replace("\r\n", "\n"))
        lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def chunk_formatted_message(
    text: str,
    *,
    template: str,
    sender_name: str,
) -> list[str]:
    base_render = template.format(name=sender_name, message="")
    overhead = len(base_render)
    allowance = 3900 - overhead
    if allowance <= 0:
        allowance = max(3900 // 2, 512)
    if len(text) <= allowance:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= allowance:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(line) > allowance:
            for start in range(0, len(line), allowance):
                chunks.append(line[start : start + allowance])
            current = ""
        else:
            current = line
    if current:
        chunks.append(current)
    return chunks


def format_plain_answer(text: str) -> str:
    return html.escape(text, quote=False).replace("\r\n", "\n")
