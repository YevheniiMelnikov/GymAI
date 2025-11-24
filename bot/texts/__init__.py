from .resources import ButtonText, MessageText
from .text_manager import TextManager, msg_text as msg_text, btn_text as btn_text

__all__: tuple[str, ...] = ("TextManager", "msg_text", "btn_text", "MessageText", "ButtonText")

TextManager.load_resources()
