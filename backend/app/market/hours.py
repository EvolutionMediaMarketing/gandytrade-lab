"""Rough trading hours, to explain when a closed market opens again.

Public holidays and early closes aren't included, so this is a guide for messages only;
whether a price is live is always judged from the data itself.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UK = ZoneInfo("Europe/London")


def _next_us_open(now_ny: datetime) -> datetime:
    if now_ny.weekday() < 5 and (9, 30) <= (now_ny.hour, now_ny.minute) < (16, 0):
        return now_ny  # open right now
    day = now_ny
    for _ in range(8):
        open_at = day.replace(hour=9, minute=30, second=0, microsecond=0)
        if day.weekday() < 5 and open_at > now_ny:
            return open_at
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
    return now_ny


def _next_fx_open(now_ny: datetime) -> datetime:
    """Forex and CFDs on OANDA: Sunday 17:00 to Friday 17:00 New York time, with a short daily pause at 17:00."""
    wd = now_ny.weekday()  # Monday = 0
    if wd == 5 or (wd == 4 and now_ny.hour >= 17) or (wd == 6 and now_ny.hour < 17):
        days = (6 - wd) % 7
        return (now_ny + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    # Inside the week: the daily pause ends a few minutes after 17:00.
    pause_end = now_ny.replace(hour=17, minute=5, second=0, microsecond=0)
    return pause_end if now_ny < pause_end and now_ny.hour == 17 else now_ny


def hours_text(provider: str, asset_class: str) -> str:
    if provider == "twelvedata":
        return "US shares trade 14:30 to 21:00 UK time on weekdays"
    if provider == "alphavantage":
        return "London shares trade 08:00 to 16:30 UK time on weekdays"
    return "This market trades from Sunday evening to Friday evening (about 22:00 UK time each way)"


def next_open(provider: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UK)
    ny = now.astimezone(NY)
    if provider == "twelvedata":
        return _next_us_open(ny).astimezone(UK)
    if provider == "oanda":
        return _next_fx_open(ny).astimezone(UK)
    return None


def closed_message(provider: str, asset_class: str, last_price_at: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(UK)
    last = last_price_at.astimezone(UK).strftime("%a %d %b %H:%M")
    text = f"The market's closed: the last price was at {last} UK time. {hours_text(provider, asset_class)}."
    opens = next_open(provider, now)
    if opens is None or opens <= now + timedelta(minutes=1):
        return (text + " It should be open now, so this may be a public holiday or a delay in the free data. "
                "Paper orders fill only on live prices.")
    wait = opens - now
    hours, minutes = divmod(int(wait.total_seconds() // 60), 60)
    when = "today" if opens.date() == now.date() else opens.strftime("%A")
    span = f"{hours} hours {minutes} minutes" if hours else f"{minutes} minutes"
    return text + f" It opens {when} at {opens.strftime('%H:%M')}, in {span}. Paper orders fill only on live prices."
