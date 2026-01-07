import html
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from core.schemas import QAResponseBlock


def parse_int_with_decimal(raw: str) -> int:
    value = (raw or "").strip().replace(",", ".")
    weight_re = re.compile(r"^\d+(?:\.\d+)?$")
    if not weight_re.fullmatch(value):
        raise ValueError("Invalid numeric value")
    try:
        return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value") from exc


def format_plain_answer(text: str) -> str:
    return html.escape(text, quote=False).replace("\r\n", "\n")


def format_answer_blocks(blocks: list[QAResponseBlock]) -> str:
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
