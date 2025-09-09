from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


def next_payment_date(period: str) -> str:
    """Return next payment date for a given period."""
    today = date.today()
    if period == "14d":
        next_date: date = today + timedelta(days=14)
    elif period == "6m":
        next_date = today + relativedelta(months=6)
    else:
        next_date = today + relativedelta(months=1)
    return next_date.strftime("%Y-%m-%d")
