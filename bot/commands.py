from aiogram.types import BotCommand

bot_commands = {  # TODO: MOVE TO TEXTS.COMMANDS.YML
    "eng": [
        BotCommand(command="/start", description="Start bot"),
        BotCommand(command="/language", description="Change language"),
        BotCommand(command="/help", description="Get help"),
        BotCommand(command="/logout", description="Logout from bot"),
    ],
    "ru": [
        BotCommand(command="/start", description="Запустить бота"),
        BotCommand(command="/language", description="Изменить язык"),
        BotCommand(command="/help", description="Получить помощь"),
        BotCommand(command="/logout", description="Выйти из бота"),
    ],
    "ua": [
        BotCommand(command="/start", description="Запустити бота"),
        BotCommand(command="/language", description="Змінити мову"),
        BotCommand(command="/help", description="Отримати допомогу"),
        BotCommand(command="/logout", description="Вийти з бота"),
    ],
}
