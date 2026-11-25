"""Horario cron legible en español para el correo (Item 079).

``humanize_cron`` traduce una expresión cron de 5 campos (la que valida
``odin.config`` con ``CronTrigger.from_crontab``) a una frase en español para el
receptor del correo, con la timezone IANA incluida. Cubre los patrones
cotidianos —hora fija diaria, días de semana y días del mes—; ante cualquier
patrón que no entienda (pasos ``*/15``, listas exóticas, rangos anidados)
devuelve el cron crudo con la timezone: exacto aunque menos amigable.

Solo stdlib y sin red: la decisión deliberada fue no sumar una dependencia
(``cron_descriptor`` y similares) para frases que además vendrían en inglés.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["humanize_cron"]

# Convención crontab para el día de la semana: 0 y 7 son domingo.
_DOW_NAMES = {
    0: "domingo",
    1: "lunes",
    2: "martes",
    3: "miércoles",
    4: "jueves",
    5: "viernes",
    6: "sábado",
    7: "domingo",
}

_MONTH_NAMES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _join_human(items: Sequence[str]) -> str:
    """Une con comas y 'y' antes del último: 'lunes, miércoles y viernes'."""
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} y {items[1]}"
    return ", ".join(items[:-1]) + f" y {items[-1]}"


def _dow_names(dow: str) -> list[str] | None:
    """Nombres de los días de la semana de un campo dow válido; ``None`` si no lo es.

    Acepta un entero, una lista separada por comas o un rango ``a-b`` (el rango
    devuelve la lista completa; el llamador usa los extremos para la frase).
    """
    if "-" in dow:
        start_raw, _, end_raw = dow.partition("-")
        start, end = _int(start_raw), _int(end_raw)
        if start is None or end is None or not (0 <= start <= end <= 7):
            return None
        names = []
        for value in range(start, end + 1):
            names.append(_DOW_NAMES[value])
        return names
    names = []
    for part in dow.split(","):
        parsed = _int(part)
        if parsed is None or parsed not in _DOW_NAMES:
            return None
        names.append(_DOW_NAMES[parsed])
    return names


def _dow_phrase(dow: str, clock: str) -> str | None:
    """Frase para un campo de día de la semana (``day`` y ``month`` en ``*``)."""
    names = _dow_names(dow)
    if names is None:
        return None
    if "-" in dow:
        return f"de {names[0]} a {names[-1]} a las {clock}"
    plural = [name if name.endswith("s") else name + "s" for name in names]
    return f"los {_join_human(plural)} a las {clock}"


def _dom_phrase(day: str, clock: str) -> str | None:
    """Frase para un campo de día del mes (``month`` y ``dow`` en ``*``)."""
    single = _int(day)
    if single is not None:
        if not 1 <= single <= 31:
            return None
        return f"el día {single} de cada mes a las {clock}"
    if "," in day:
        values = [_int(part) for part in day.split(",")]
        if any(value is None or not 1 <= value <= 31 for value in values):
            return None
        return f"los días {_join_human([str(value) for value in values])} de cada mes a las {clock}"
    return None


def humanize_cron(schedule: str, timezone: str) -> str:
    """Traduce ``schedule`` (cron de 5 campos) a una frase en español con ``timezone``.

    Ejemplos: ``0 3 * * *`` → ``todos los días a las 03:00 (America/Caracas)``;
    ``30 9 * * 1-5`` → ``de lunes a viernes a las 09:30 (...)``; ``0 2 1 * *`` →
    ``el día 1 de cada mes a las 02:00 (...)``. Lo que no entiende se devuelve
    crudo: ``{schedule} ({timezone})``.
    """
    fields = schedule.split()
    if len(fields) != 5:
        return f"{schedule} ({timezone})"
    minute, hour, day, month, dow = fields
    minute_value, hour_value = _int(minute), _int(hour)
    if (
        minute_value is None
        or hour_value is None
        or not (0 <= minute_value <= 59 and 0 <= hour_value <= 23)
    ):
        return f"{schedule} ({timezone})"
    clock = f"{hour_value:02d}:{minute_value:02d}"

    phrase: str | None = None
    if day == "*" and month == "*" and dow == "*":
        phrase = f"todos los días a las {clock}"
    elif day == "*" and month == "*":
        phrase = _dow_phrase(dow, clock)
    elif month == "*" and dow == "*":
        phrase = _dom_phrase(day, clock)
    elif dow == "*":
        month_value, day_value = _int(month), _int(day)
        if (
            month_value is not None
            and day_value is not None
            and 1 <= month_value <= 12
            and 1 <= day_value <= 31
        ):
            phrase = f"el {day_value} de {_MONTH_NAMES[month_value]} a las {clock}"

    if phrase is None:
        return f"{schedule} ({timezone})"
    return f"{phrase} ({timezone})"
