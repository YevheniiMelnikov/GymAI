from .resources import ButtonText, MessageText
from .text_manager import TextManager, translate as translate

__all__: tuple[str, ...] = ("TextManager", "translate", "MessageText", "ButtonText")

TextManager.load_resources()
