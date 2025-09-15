from datetime import date
from dateutil.relativedelta import relativedelta
from typing import cast

from core.enums import SubscriptionPeriod


def next_payment_date(period: SubscriptionPeriod = SubscriptionPeriod.one_month) -> str:
    """Return next payment date for a given period."""
    today = date.today()
    if period is SubscriptionPeriod.six_months:
        next_date = cast(date, today + relativedelta(months=6))  # pyrefly: ignore[redundant-cast]
    else:
        next_date = cast(date, today + relativedelta(months=1))  # pyrefly: ignore[redundant-cast]
    return next_date.strftime("%Y-%m-%d")
