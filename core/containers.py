from dependency_injector import containers, providers
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties


class App(containers.DeclarativeContainer):
    config = providers.Configuration()
    bot = providers.Singleton(
        Bot,
        token=config.bot_token,
        default=providers.Callable(DefaultBotProperties, parse_mode=config.parse_mode),
    )
