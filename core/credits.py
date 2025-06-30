from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from config.env_settings import settings


@dataclass(frozen=True)
class CreditPackage:
    name: str
    credits: int
    price: Decimal


def uah_to_credits(amount: Decimal, rate: Decimal) -> int:
    return int((amount / rate).quantize(Decimal("1"), ROUND_HALF_UP))


def credits_to_uah(credits: int, rate: Decimal) -> Decimal:
    return (Decimal(credits) * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def required_credits(amount: Decimal, rate: Decimal) -> int:
    return uah_to_credits(amount * Decimal("1.3"), rate)


def available_packages() -> list[CreditPackage]:
    return [
        CreditPackage("start", settings.PACKAGE_START_CREDITS, settings.PACKAGE_START_PRICE),
        CreditPackage("optimum", settings.PACKAGE_OPTIMUM_CREDITS, settings.PACKAGE_OPTIMUM_PRICE),
        CreditPackage("max", settings.PACKAGE_MAX_CREDITS, settings.PACKAGE_MAX_PRICE),
    ]

def convert_uah_to_credits_flexible(
    price_uah: Decimal,
    credit_rate_max_pack: Decimal = Decimal("0.371"),
    max_markup_pct_on_cheap: Decimal = Decimal("0.30"),
    cheap_price_threshold: Decimal = Decimal("1500")
) -> int:
    """
    Конвертирует цену в грн в кредиты, которые будут списаны с клиента,
    учитывая адаптивную маржу: не больше 30% для дешевых услуг,
    и ограничение сверху по сравнению с "макс" тарифом.

    :param price_uah: Цена от тренера (в гривнах)
    :param credit_rate_max_pack: Сколько стоит 1 кредит для клиента на "макс" пакете
    :param max_markup_pct_on_cheap: Максимальная маржа на дешевых ценах (например, 30%)
    :param cheap_price_threshold: До какой суммы считаем "дешево"
    :return: Количество кредитов для отображения клиенту
    """
    # Себестоимость: сколько кредитов необходимо, чтобы покрыть цену тренера
    raw_credits_needed = price_uah / credit_rate_max_pack

    # При дешевых услугах — можно добавить маржу до 30%
    if price_uah <= cheap_price_threshold:
        credits_with_markup = raw_credits_needed * (1 + max_markup_pct_on_cheap)
    else:
        # При дорогих — маржа снижается логарифмически (или можно просто зафиксировать)
        # Например, у нас ограничение — не выходить за предел "стоимость по макс-пакету"
        # Поэтому просто округляем кредиты вверх (для защиты прибыли)
        credits_with_markup = raw_credits_needed.quantize(Decimal("1."), rounding=ROUND_HALF_UP)

    return int(credits_with_markup.to_integral_value(rounding=ROUND_HALF_UP))
