"""Logging de ODIN: archivo con rotación, consola opcional y enmascarado (Items 004 y 064).

Solo stdlib (``logging``, ``logging.handlers``, ``re``, ``pathlib``).
``setup_logging`` configura el logger ``odin``: un ``RotatingFileHandler``
sobre ``<resolved_log_dir>/odin.log`` (codificación UTF-8) y, con
``console=True`` (default), un ``StreamHandler``; ambos con formato
``timestamp | nivel | logger | mensaje`` y nivel efectivo tomado de
``config.local.log_level``. El modo servicio residente usa ``console=False``
(Item 064): bajo el SCM o systemd no hay handles de consola y el registro debe
quedar solo en el archivo rotado. El directorio de logs (``local.log_dir`` o el
default ``<work_dir>/logs``) se crea si no existe.

Rotación: ``DEFAULT_MAX_BYTES`` (5 MiB) por archivo con
``DEFAULT_BACKUP_COUNT`` (5) backups. Defaults sensatos para respaldos
diarios sin consumo excesivo de disco; no se exponen en el JSON para no
sumar superficie de configuración en la Etapa 1.

``redirect_stdio_to_log`` (Item 064) redirige ``sys.stdout``/``sys.stderr`` al
log durante un bloque para que un ``print`` perdido del proceso residente no
falle sin consola; si el archivo no es escribible el texto se descarta.

Enmascarado (visión §6 Seguridad): ``SecretMasker`` es una utilidad pura
(sin efectos secundarios al importar, no toca el logger global) que
reemplaza por ``***`` cada secreto no vacío de
``Config.iter_secret_fields()`` y vacía el cuerpo de bloques PEM
``PRIVATE KEY`` aunque su contenido no esté listado. Se reutiliza como segunda
barrera en los correos de ejecución de la Etapa 5 (``odin.notify``) y en los
resúmenes de consola enmascarados de ``odin.cli``.

Cola de log del informe (Item 041): ``TailBufferHandler`` captura las últimas
``notification.log_tail_lines`` líneas ya formateadas en un
``deque(maxlen=N)``, aplicando el ``MaskingFilter`` con el ``SecretMasker``
de la configuración como barrera propia (independiente del orden de handlers
del logger). ``capture_log_tail`` es el context manager recomendado para
adjuntarlo/removerlo del logger ``odin`` alrededor de una corrida;
``notification.log_tail_lines == 0`` desactiva la captura.

Política de secretos cortos: los literales con menos de
``MIN_SECRET_LENGTH`` (4) caracteres se ignoran. Enmascarar literales de
1-3 caracteres (p. ej. ``a`` o ``7``) destruiría la legibilidad del log
por falsos positivos sin beneficio real: una credencial tan corta es
débil y debe corregirse en la configuración, no ocultarse en el log.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from odin.config import Config, LogLevel

LOGGER_NAME = "odin"
logger = logging.getLogger(LOGGER_NAME)

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
    "TailBufferHandler",
    "attach_tail_buffer",
    "capture_log_tail",
    "detach_tail_buffer",
    "redirect_stdio_to_log",
    "setup_logging",
]


LOGGER_NAME = "odin"
LOG_FILENAME = "odin.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
MASK = "***"
MIN_SECRET_LENGTH = 4

_PEM_RE = re.compile(
    r"(-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----).*?(-----END \2-----|\Z)",
    re.DOTALL,
)

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
        return _PEM_RE.sub(rf"\1{MASK}\3", masked)


class MaskingFilter(logging.Filter):
    """Filtro de logging que enmascara secretos sobre el mensaje ya interpolado."""

    def __init__(self, masker: SecretMasker) -> None:
        super().__init__()
        self._masker = masker

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._masker.mask(record.getMessage())
        record.args = None
        return True


def setup_logging(config: Config, *, console: bool = True) -> logging.Logger:
    """Configura el logger ``odin`` con archivo rotado y consola opcional.

    Idempotente: re-invocarla (p. ej. recarga en caliente del modo
    servicio, Etapa 6) cierra y remueve los handlers previos antes de
    crear los nuevos, sin duplicar salidas. El logger no propaga al root
    para evitar líneas duplicadas si otro componente configura el root.

    ``console=True`` (default) agrega el ``StreamHandler`` histórico —lo que
    usa ``odin service run`` en primer plano—; ``console=False`` (Item 064)
    registra **solo** a archivo: el servicio residente corre bajo el SCM de
    Windows o systemd, sin handles de consola. El archivo conserva la rotación
    (5 MiB × 5 backups) y el ``MaskingFilter`` en ambos modos.
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

    logger.addHandler(file_handler)
    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(masking)
        logger.addHandler(stream_handler)
    return logger


class _LogStream:
    """File-like que agrega al log, o descarta el texto si no es escribible.

    Lo instala ``redirect_stdio_to_log`` (Item 064): existe para que un
    ``print`` perdido del servicio residente —sin handles de consola— no falle
    con ``OSError``/``AttributeError``. No enmascara secretos: esa barrera es
    responsabilidad de los handlers del logger (``MaskingFilter``).
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def write(self, text: str) -> int:
        """Agrega ``text`` al archivo; si no se puede, lo descarta en silencio."""
        if not text:
            return 0
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        """No-op: cada ``write`` abre y cierra el archivo."""

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"


@contextmanager
def redirect_stdio_to_log(path: Path | str) -> Iterator[Path]:
    """Redirige ``sys.stdout``/``sys.stderr`` al log durante el bloque (Item 064).

    Reemplaza ambos streams por un writer que agrega al archivo indicado
    (típicamente ``<resolved_log_dir>/odin.log``) y los restaura al salir,
    incluso ante excepción. Es la red de seguridad del servicio residente:
    bajo el SCM de Windows o systemd no hay handles de consola y un ``print``
    perdido no debe tumbar el proceso. Si el archivo no es escribible
    (``OSError``), el writer descarta el texto (sumidero seguro). Devuelve la
    ruta objetivo.
    """
    target = Path(path)
    writer = _LogStream(target)
    previous_out, previous_err = sys.stdout, sys.stderr
    sys.stdout = writer
    sys.stderr = writer
    try:
        yield target
    finally:
        sys.stdout = previous_out
        sys.stderr = previous_err


class TailBufferHandler(logging.Handler):
    """Captura en memoria las últimas ``maxlen`` líneas de log formateadas.

    Pensado para adjuntar el tramo final del log al correo de ejecución
    (Item 041): el ``deque(maxlen)`` retiene solo lo reciente y descarta lo
    más antiguo sin crecimiento de memoria. Con ``masker`` se agrega un
    ``MaskingFilter`` propio para que el buffer nunca conserve secretos,
    aunque el handler se evalúe antes que los handlers enmascaradores del
    logger. ``maxlen == 0`` desactiva la captura (el deque no retiene nada).
    """

    def __init__(self, maxlen: int, masker: SecretMasker | None = None) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=max(0, maxlen))
        self.setFormatter(logging.Formatter(LOG_FORMAT))
        if masker is not None:
            self.addFilter(MaskingFilter(masker))

    def emit(self, record: logging.LogRecord) -> None:
        """Formatea el record y lo agrega al buffer (descarta el más antiguo)."""
        try:
            self._lines.append(self.format(record))
        except Exception:
            self.handleError(record)

    @property
    def lines(self) -> tuple[str, ...]:
        """Líneas capturadas en orden cronológico (la más reciente al final)."""
        return tuple(self._lines)

    def clear(self) -> None:
        """Vacía el buffer sin desadjuntar el handler."""
        self._lines.clear()


def _resolve_target(target: logging.Logger | None) -> logging.Logger:
    """Logger objetivo de la captura: el indicado o el logger ``odin``."""
    return target if target is not None else logging.getLogger(LOGGER_NAME)


def attach_tail_buffer(
    handler: TailBufferHandler, target: logging.Logger | None = None
) -> TailBufferHandler:
    """Adjunta ``handler`` al logger ``odin`` (o al indicado) y lo devuelve."""
    _resolve_target(target).addHandler(handler)
    return handler


def detach_tail_buffer(handler: TailBufferHandler, target: logging.Logger | None = None) -> None:
    """Remueve ``handler`` del logger ``odin`` (o del indicado)."""
    _resolve_target(target).removeHandler(handler)


@contextmanager
def capture_log_tail(
    maxlen: int, masker: SecretMasker | None = None, *, target: logging.Logger | None = None
) -> Iterator[TailBufferHandler]:
    """Captura la cola del log durante el bloque y remueve el handler al salir.

    Con ``maxlen <= 0`` no adjunta nada y devuelve un buffer vacío (la captura
    queda deshabilitada, ``notification.log_tail_lines == 0``). La remoción
    está en ``finally``: una excepción dentro del bloque no deja el handler
    colgado en el logger.
    """
    handler = TailBufferHandler(maxlen, masker)
    if maxlen > 0:
        attach_tail_buffer(handler, target)
    try:
        yield handler
    finally:
        if maxlen > 0:
            detach_tail_buffer(handler, target)
        handler.close()
