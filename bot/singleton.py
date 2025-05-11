from aiogram import Bot

bot: Bot | None = None


def set_bot(instance: Bot) -> None:
    global bot
    bot = instance
