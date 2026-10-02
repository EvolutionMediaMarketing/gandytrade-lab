from datetime import datetime
from zoneinfo import ZoneInfo

from app.market.hours import closed_message, next_open

UK = ZoneInfo("Europe/London")


def test_us_shares_open_at_1430_uk_on_a_weekday_morning():
    now = datetime(2026, 10, 2, 11, 5, tzinfo=UK)  # Friday
    assert next_open("twelvedata", now) == datetime(2026, 10, 2, 14, 30, tzinfo=UK)
    msg = closed_message("twelvedata", "stock", datetime(2026, 10, 1, 21, 0, tzinfo=UK), now)
    assert "opens today at 14:30, in 3 hours 25 minutes" in msg


def test_us_shares_after_friday_close_open_on_monday():
    now = datetime(2026, 10, 2, 21, 30, tzinfo=UK)
    assert next_open("twelvedata", now) == datetime(2026, 10, 5, 14, 30, tzinfo=UK)


def test_forex_weekend_opens_sunday_evening():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UK)  # Saturday
    opens = next_open("oanda", now)
    assert opens.weekday() == 6 and opens.hour == 22  # Sunday 17:00 New York = 22:00 UK in October


def test_open_but_stale_suggests_holiday_or_delay():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=UK)  # US market should be open
    msg = closed_message("twelvedata", "stock", datetime(2026, 10, 1, 21, 0, tzinfo=UK), now)
    assert "public holiday or a delay" in msg
