from aiogram.types import BotCommand

bot_commands = {  # TODO: MOVE TO TEXTS.COMMANDS.YML
    "eng": [
        BotCommand(command="/start", description="Start bot"),
        BotCommand(command="/language", description="Change language"),
        BotCommand(command="/help", description="Help"),
        BotCommand(command="/logout", description="Logout from bot"),
        BotCommand(command="/reset_password", description="Reset password"),
    ],
    "ru": [
        BotCommand(command="/start", description="Запустить бота"),
        BotCommand(command="/language", description="Изменить язык"),
        BotCommand(command="/help", description="Помощь"),
        BotCommand(command="/logout", description="Выйти из бота"),
        BotCommand(command="/reset_password", description="Сбросить пароль"),
    ],
    "ua": [
        BotCommand(command="/start", description="Запустити бота"),
        BotCommand(command="/language", description="Змінити мову"),
        BotCommand(command="/help", description="Допомога"),
        BotCommand(command="/logout", description="Вийти з бота"),
        BotCommand(command="/reset_password", description="Скинути пароль"),
    ],
}
