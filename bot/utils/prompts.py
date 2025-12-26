from pathlib import Path

from aiogram.types import CallbackQuery, Message, FSInputFile
from loguru import logger

from bot.keyboards import enter_wishes_kb
from bot.texts import MessageText, translate
from bot.utils.bot import BotMessageProxy, answer_msg, get_webapp_url
from config.app_settings import settings

InteractionTarget = CallbackQuery | Message | BotMessageProxy


async def send_enter_wishes_prompt(
    target: InteractionTarget,
    language: str,
    *,
    webapp_url: str | None = None,
) -> Message | None:
    prompt_text = translate(MessageText.enter_wishes, language).format(bot_name=settings.BOT_NAME)
    resolved_webapp_url = webapp_url or get_webapp_url("program", language)
    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_workouts.png"
    if file_path.exists():
        return await answer_msg(
            target,
            caption=prompt_text,
            photo=FSInputFile(file_path),
            reply_markup=enter_wishes_kb(language, resolved_webapp_url),
        )
    logger.warning(f"event=enter_wishes_image_missing path={file_path}")
    return await answer_msg(
        target,
        prompt_text,
        reply_markup=enter_wishes_kb(language, resolved_webapp_url),
    )
