"""Tests del horario cron legible en español (Item 079)."""

from odin.cron_phrase import humanize_cron


def test_every_day_at_fixed_time() -> None:
    assert humanize_cron("0 3 * * *", "America/Caracas") == (
        "todos los días a las 03:00 (America/Caracas)"
    )


def test_weekdays_range() -> None:
    assert humanize_cron("30 9 * * 1-5", "UTC") == "de lunes a viernes a las 09:30 (UTC)"


def test_single_weekday() -> None:
    assert humanize_cron("0 2 * * 0", "UTC") == "los domingos a las 02:00 (UTC)"


def test_sunday_as_seven() -> None:
    assert humanize_cron("0 2 * * 7", "UTC") == "los domingos a las 02:00 (UTC)"


def test_weekday_list() -> None:
    assert humanize_cron("0 7 * * 1,3,5", "UTC") == (
        "los lunes, miércoles y viernes a las 07:00 (UTC)"
    )


def test_two_weekdays_use_y() -> None:
    assert humanize_cron("0 7 * * 1,5", "UTC") == "los lunes y viernes a las 07:00 (UTC)"


def test_day_of_month() -> None:
    assert humanize_cron("0 2 1 * *", "UTC") == "el día 1 de cada mes a las 02:00 (UTC)"


def test_day_of_month_list() -> None:
    assert humanize_cron("0 2 1,15 * *", "UTC") == (
        "los días 1 y 15 de cada mes a las 02:00 (UTC)"
    )


def test_specific_month_day() -> None:
    assert humanize_cron("0 0 25 12 *", "UTC") == "el 25 de diciembre a las 00:00 (UTC)"


def test_step_falls_back_to_raw_cron() -> None:
    assert humanize_cron("*/15 * * * *", "UTC") == "*/15 * * * * (UTC)"


def test_minute_range_falls_back_to_raw_cron() -> None:
    assert humanize_cron("0-30 3 * * *", "UTC") == "0-30 3 * * * (UTC)"


def test_hour_list_falls_back_to_raw_cron() -> None:
    assert humanize_cron("0 2,14 * * *", "UTC") == "0 2,14 * * * (UTC)"


def test_dom_and_dow_together_falls_back_to_raw_cron() -> None:
    assert humanize_cron("0 2 1 * 1", "UTC") == "0 2 1 * 1 (UTC)"


def test_invalid_field_count_falls_back() -> None:
    assert humanize_cron("0 3 * *", "UTC") == "0 3 * * (UTC)"


def test_out_of_range_hour_falls_back() -> None:
    assert humanize_cron("0 25 * * *", "UTC") == "0 25 * * * (UTC)"
