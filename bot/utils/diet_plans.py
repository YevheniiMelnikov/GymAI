import html
from typing import Iterable

from core.schemas import DietPlan, NutritionTotals

DIET_PRODUCT_CALLBACK_PREFIX = "diet_product_"
DIET_PRODUCTS_DONE = "diet_products_done"
DIET_PRODUCTS_BACK = "diet_products_back"
DIET_RESULT_REPEAT = "diet_repeat"
DIET_RESULT_MENU = "diet_main_menu"

DIET_PRODUCT_OPTIONS: tuple[str, ...] = (
    "plant_food",
    "meat",
    "fish_seafood",
    "eggs",
    "dairy",
)


def normalize_diet_products(raw: object) -> list[str]:
    if isinstance(raw, (str, bytes)):
        return []
    if not isinstance(raw, Iterable):
        return []
    items = [item for item in raw if isinstance(item, str)]
    allowed = {item for item in items if item in DIET_PRODUCT_OPTIONS}
    return [item for item in DIET_PRODUCT_OPTIONS if item in allowed]


def toggle_diet_product(selected: list[str], product: str) -> list[str]:
    normalized = normalize_diet_products(selected)
    selected_set = set(normalized)
    if product in selected_set:
        selected_set.remove(product)
    else:
        selected_set.add(product)
    return [item for item in DIET_PRODUCT_OPTIONS if item in selected_set]


def _label_map(lang: str) -> dict[str, str]:
    return {
        "eng": {
            "summary": "Summary",
            "calories": "Calories",
            "protein": "Protein",
            "fat": "Fat",
            "carbs": "Carbs",
            "grams_unit": "g",
            "kcal_unit": "kcal",
            "notes": "Notes",
        },
        "ru": {
            "summary": "Сводка КБЖУ",
            "calories": "Калории",
            "protein": "Белки",
            "fat": "Жиры",
            "carbs": "Углеводы",
            "grams_unit": "г",
            "kcal_unit": "ккал",
            "notes": "Заметки",
        },
        "ua": {
            "summary": "Підсумок КБЖУ",
            "calories": "Калорії",
            "protein": "Білки",
            "fat": "Жири",
            "carbs": "Вуглеводи",
            "grams_unit": "г",
            "kcal_unit": "ккал",
            "notes": "Примітки",
        },
    }.get(
        lang,
        {
            "summary": "Summary",
            "calories": "Calories",
            "protein": "Protein",
            "fat": "Fat",
            "carbs": "Carbs",
            "grams_unit": "g",
            "kcal_unit": "kcal",
            "notes": "Notes",
        },
    )


def _format_float(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_summary(totals: NutritionTotals, labels: dict[str, str]) -> list[str]:
    return [
        f"{labels['calories']}: {totals.calories} {labels['kcal_unit']}",
        f"{labels['protein']}: {_format_float(totals.protein_g)} {labels['grams_unit']}",
        f"{labels['fat']}: {_format_float(totals.fat_g)} {labels['grams_unit']}",
        f"{labels['carbs']}: {_format_float(totals.carbs_g)} {labels['grams_unit']}",
    ]


def format_diet_plan(plan: DietPlan, lang: str) -> str:
    labels = _label_map(lang)
    lines: list[str] = []
    for meal in plan.meals:
        name = html.escape(meal.name or "", quote=False)
        if name:
            lines.append(f"<b>{name}</b>")
        for item in meal.items:
            item_name = html.escape(item.name or "", quote=False)
            line = f"- {item_name} — {item.grams} {labels['grams_unit']}"
            lines.append(line)
        lines.append("")
    if plan.notes:
        lines.append("")
        lines.append(f"<b>{labels['notes']}:</b>")
        for note in plan.notes:
            note_text = html.escape(note, quote=False)
            if note_text:
                lines.append(f"- {note_text}")
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append("")
    lines.append(f"<b>{labels['summary']}:</b>")
    lines.extend(_format_summary(plan.totals, labels))
    return "\n".join(lines)
