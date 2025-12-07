from datetime import date
from dateutil.relativedelta import relativedelta
from typing import cast

from core.enums import SubscriptionPeriod


def next_payment_date(period: SubscriptionPeriod = SubscriptionPeriod.one_month) -> str:
    """Return next payment date for a given period."""
    today = date.today()
    if period is SubscriptionPeriod.six_months:
        delta_months = 6
    elif period is SubscriptionPeriod.twelve_months:
        delta_months = 12
    else:
        delta_months = 1
    next_date = cast(date, today + relativedelta(months=delta_months))  # pyrefly: ignore[redundant-cast]
    return next_date.strftime("%Y-%m-%d")
