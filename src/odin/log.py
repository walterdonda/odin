"""Logging de ODIN: consola + archivo con rotación y enmascarado de secretos (Item 004).

Solo stdlib (``logging``, ``logging.handlers``, ``re``, ``pathlib``).
``setup_logging`` configura el logger ``odin`` con dos handlers: consola
(``StreamHandler``) y archivo (``RotatingFileHandler`` sobre
``<resolved_log_dir>/odin.log``, codificación UTF-8), ambos con formato
``timestamp | nivel | logger | mensaje`` y nivel efectivo tomado de
``config.local.log_level``. El directorio de logs (``local.log_dir`` o el
default ``<work_dir>/logs``) se crea si no existe.

Rotación: ``DEFAULT_MAX_BYTES`` (5 MiB) por archivo con
``DEFAULT_BACKUP_COUNT`` (5) backups. Defaults sensatos para respaldos
diarios sin consumo excesivo de disco; no se exponen en el JSON para no
sumar superficie de configuración en la Etapa 1.

Enmascarado (visión §6 Seguridad): ``SecretMasker`` es una utilidad pura
(sin efectos secundarios al importar, no toca el logger global) que
reemplaza por ``***`` cada secreto no vacío de
``Config.iter_secret_fields()`` y vacía el cuerpo de bloques PEM
``PRIVATE KEY`` aunque su contenido no esté listado. Está pensada para
reutilizarse en los correos de ejecución de la Etapa 5.

Política de secretos cortos: los literales con menos de
``MIN_SECRET_LENGTH`` (4) caracteres se ignoran. Enmascarar literales de
1-3 caracteres (p. ej. ``a`` o ``7``) destruiría la legibilidad del log
por falsos positivos sin beneficio real: una credencial tan corta es
débil y debe corregirse en la configuración, no ocultarse en el log.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from logging.handlers import RotatingFileHandler

from odin.config import Config, LogLevel

__all__ = [
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_MAX_BYTES",
    "LOG_FILENAME",
    "LOG_FORMAT",
    "LOGGER_NAME",
    "MASK",
    "MIN_SECRET_LENGTH",
    "MaskingFilter",
    "SecretMasker",
    "setup_logging",
]

LOGGER_NAME = "odin"
LOG_FILENAME = "odin.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
MASK = "***"
MIN_SECRET_LENGTH = 4

_PEM_PAIR_RE = re.compile(
    r"(-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----).*?(-----END \2-----)",
    re.DOTALL,
)
_PEM_OPEN_RE = re.compile(r"(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----).*\Z", re.DOTALL)

_LEVELS: Mapping[LogLevel, int] = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}


class SecretMasker:
    """Enmascara secretos literales y bloques PEM de claves privadas.

    Los secretos se reemplazan por ``MASK`` de más largo a más corto para
    evitar solapamientos parciales (si ``abc`` y ``abcdef`` son secretos,
    ``abcdef`` se enmascara completo, no queda ``***def``). Se ignoran los
    valores vacíos (enmascarar la cadena vacía destruiría todo el texto) y
    los menores a ``MIN_SECRET_LENGTH`` (ver docstring del módulo).

    Bloques PEM: se vacía el cuerpo entre ``-----BEGIN ...PRIVATE KEY-----``
    y su ``-----END`` correspondiente; un bloque truncado sin ``END`` se
    enmascara hasta el fin del texto (postura conservadora: tras un
    marcador BEGIN no hay forma de saber dónde termina el material de la
    clave).
    """

    def __init__(self, secrets: Iterable[str]) -> None:
        collected: list[str] = []
        for secret in secrets:
            if not secret or len(secret) < MIN_SECRET_LENGTH:
                continue
            if secret not in collected:
                collected.append(secret)
        collected.sort(key=len, reverse=True)
        self._secrets = tuple(collected)

    @classmethod
    def from_config(cls, config: Config) -> SecretMasker:
        """Construye el masker con los valores de ``config.iter_secret_fields()``."""
        return cls(value for _, value in config.iter_secret_fields())

    @property
    def secrets(self) -> tuple[str, ...]:
        """Secretos efectivos a enmascarar (orden: más largo primero)."""
        return self._secrets

    def mask(self, text: str) -> str:
        """Devuelve ``text`` con los secretos literales y bloques PEM enmascarados."""
        masked = text
        for secret in self._secrets:
            masked = masked.replace(secret, MASK)
        masked = _PEM_PAIR_RE.sub(rf"\1{MASK}\3", masked)
        return _PEM_OPEN_RE.sub(rf"\1{MASK}", masked)


class MaskingFilter(logging.Filter):
    """Filtro de logging que enmascara secretos sobre el mensaje ya interpolado."""

    def __init__(self, masker: SecretMasker) -> None:
        super().__init__()
        self._masker = masker

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._masker.mask(record.getMessage())
        record.args = None
        return True


def setup_logging(config: Config) -> logging.Logger:
    """Configura el logger ``odin`` con consola + archivo rotado y devuelve el logger.

    Idempotente: re-invocarla (p. ej. recarga en caliente del modo
    servicio, Etapa 6) cierra y remueve los handlers previos antes de
    crear los nuevos, sin duplicar salidas. El logger no propaga al root
    para evitar líneas duplicadas si otro componente configura el root.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    level = _LEVELS[config.local.log_level]
    logger.setLevel(level)
    logger.propagate = False

    log_dir = config.local.resolved_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)
    masking = MaskingFilter(SecretMasker.from_config(config))

    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(masking)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(masking)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
