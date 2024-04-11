from aiogram.types import BotCommand

bot_commands = [
    BotCommand(command="/start", description="Start bot"),
    BotCommand(command="/language", description="Change language"),
    BotCommand(command="/help", description="Get help"),
    BotCommand(command="/logout", description="Logout from bot"),
]
