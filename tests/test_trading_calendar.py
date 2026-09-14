from datetime import date

from backend.app.data.trading_calendar import TradingCalendarProvider


def test_count_between_returns_none_when_calendar_empty():
    provider = TradingCalendarProvider(trade_dates=[])

    assert provider.count_between(date(2025, 1, 1), date(2025, 1, 7)) is None


def test_count_between_returns_none_when_calendar_does_not_cover_window():
    # Earliest known trade date is after the window start -> cannot prove coverage.
    provider = TradingCalendarProvider(trade_dates=[date(2025, 1, 3)])

    assert provider.count_between(date(2025, 1, 1), date(2025, 1, 7)) is None


def test_count_between_counts_only_when_calendar_covers_window():
    provider = TradingCalendarProvider(
        trade_dates=[date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
    )

    assert provider.count_between(date(2025, 1, 2), date(2025, 1, 6)) == 3
    assert provider.count_between(date(2025, 1, 3), date(2025, 1, 5)) == 1


def test_as_callable_is_injectable_as_trading_days():
    provider = TradingCalendarProvider(trade_dates=[date(2025, 1, 2), date(2025, 1, 3)])

    trading_days = provider.as_callable()

    assert trading_days(date(2025, 1, 2), date(2025, 1, 3)) == 2


def test_refresh_reloads_calendar():
    calls = []

    def fetch():
        calls.append(1)
        return [date(2025, 1, 2)]

    provider = TradingCalendarProvider(fetch=fetch)
    provider.get_trade_dates()
    assert len(calls) == 1

    provider.refresh()
    assert len(calls) == 2
