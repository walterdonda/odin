"""Scheduler interno de ODIN sobre APScheduler 3.x (Items 049-054).

Contenido:

- Helpers de calendario (Item 049): ``cron_trigger`` construye el
  ``CronTrigger`` de APScheduler 3.x para una expresión cron de 5 campos y una
  timezone IANA; ``next_fire_times`` calcula de forma determinista los próximos
  disparos a partir de un ``now`` inyectable. La validación de las expresiones
  en ``odin.config`` usa el mismo ``CronTrigger.from_crontab``: lo que acepta la
  configuración es exactamente lo que el scheduler podrá programar.
- ``SchedulerService`` (Item 050): ``BlockingScheduler`` con la timezone global
  del JSON, un job APScheduler por ``scheduler.jobs[]`` (id estable ``job-N``,
  ``max_instances=1``, ``replace_existing=True``) y ciclo de vida
  ``start()``/``shutdown()`` con logging. La ejecución de un ciclo delega en un
  ``cycle_runner`` inyectable de interfaz ``(Config, SchedulerJob) ->
  CycleOutcome``: el núcleo no conoce el pipeline (el runner real sobre
  ``run_pipeline`` llega en el Item 054) y es testeable sin red ni reloj real.
- Anti-solapamiento y misfire (Item 051): registro in-flight por base con
  ``threading.Lock`` y semántica ``skip_if_running``/``on_misfire``.
- Estado consultable del servicio (Item 052): ``ServiceState``/``JobState``/
  ``CycleRecord`` con escritura atómica en ``work_dir/scheduler_state.json``,
  lectura tolerante (``load_state``) y detección de estado obsoleto por ``pid``;
  ``SchedulerStateStore`` es el acumulador que el servicio y la CLI usan.
- Runner real del ciclo (Item 054): ``PipelineCycleRunner`` filtra las bases
  del job, arma la config del ciclo con ``replace`` y ejecuta ``run_pipeline``
  (correo y retención propios) traduciendo su resultado a ``CycleOutcome``; el
  aislamiento de excepciones y la persistencia quedan en el servicio.
- Recarga en caliente (Item 055): ``SchedulerService.request_reload()`` marca
  una bandera thread-safe (la usa el manejador de ``SIGUSR1`` que instala la
  CLI en POSIX) y el job interno ``reload-watcher`` consume también el archivo
  de control ``work_dir/scheduler_reload.request`` (plataformas sin señales).
  ``process_reload()`` valida la configuración editada con ``load_config`` +
  ``validate_config``: si es válida reemplaza la vigente, actualiza la timezone
  y re-registra los jobs con sus próximos disparos sin detener el scheduler; si
  es inválida conserva la vigente y registra el motivo en el log y en el
  estado.

Decisión de implementación (Item 050): **APScheduler 3.11.3** por sobre 4.x y la
stdlib.

- 3.11.3 es la serie lockeada y verificada en Python 3.14 por el Item 008, con
  ``BlockingScheduler`` estable, ``CronTrigger.from_crontab``, ``timezone``
  IANA, ``max_instances``/``coalesce``/``misfire_grace_time`` y reemplazo de
  jobs en caliente (``replace_existing``), justo lo que necesitan los Items
  049-058.
- La serie 4.x sigue en pre-release (API nueva de ``Scheduler`` sin paridad
  documentada de ``BlockingScheduler`` ni de los job defaults); adoptarla
  habría cambiado el lock verificado y toda la superficie de tests.
- La stdlib no trae un planificador con cron + ``ZoneInfo``, coalescing de
  disparos vencidos y política de instancias: reimplementarlo sería más código
  propio (y peor probado) para el mismo comportamiento.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from odin.backup import BackupResult
from odin.config import Config, ConfigError, MisfirePolicy, SchedulerJob, load_config
from odin.log import SecretMasker
from odin.pipeline import PipelineResult, run_pipeline

__all__ = [
    "MAX_RECENT_ERRORS",
    "RELOAD_POLL_SECONDS",
    "RELOAD_REQUEST_FILENAME",
    "RELOAD_WATCHER_JOB_ID",
    "SCHEMA_VERSION",
    "STATE_FILENAME",
    "CycleOutcome",
    "CycleRecord",
    "CycleStatus",
    "InFlightRegistry",
    "JobState",
    "PipelineCycleRunner",
    "Reservation",
    "SchedulerService",
    "SchedulerStateStore",
    "ServiceState",
    "StateLoadResult",
    "cron_trigger",
    "load_state",
    "next_fire_times",
    "pid_is_alive",
    "reload_request_path",
    "render_service_status",
    "state_path",
    "write_state",
]

logger = logging.getLogger(__name__)

# Tolerancia de latencia de un disparo en segundos (Item 051): un job con
# on_misfire=skip que se ejecuta más tarde que esto se descarta; también es el
# ``misfire_grace_time`` configurado en APScheduler para esos jobs, que exige un
# entero positivo (o None).
_MISFIRE_TOLERANCE_SEC = 1

# Estado consultable del servicio (Item 052): esquema, nombre de archivo en
# ``local.work_dir`` y tope de errores recientes persistidos.
SCHEMA_VERSION = 1
STATE_FILENAME = "scheduler_state.json"
MAX_RECENT_ERRORS = 10

# Recarga en caliente (Item 055): archivo de control que la CLI usa cuando no
# hay señal (Windows), job interno que lo vigila junto con la bandera de
# ``SIGUSR1`` y cadencia de la vigilancia.
RELOAD_REQUEST_FILENAME = "scheduler_reload.request"
RELOAD_POLL_SECONDS = 2.0
RELOAD_WATCHER_JOB_ID = "reload-watcher"

CycleRunner = Callable[[Config, SchedulerJob], "CycleOutcome"]
Clock = Callable[[], datetime]


def cron_trigger(schedule: str, timezone: str) -> CronTrigger:
    """Construye el ``CronTrigger`` de ``schedule`` (5 campos) en ``timezone``.

    ``timezone`` es un nombre IANA (p. ej. ``America/Argentina/Buenos_Aires``).
    Lanza ``ValueError`` si la expresión cron es inválida o está fuera de rango
    y ``ZoneInfoNotFoundError`` si la timezone no existe; la validación de
    configuración (``odin.config``) reporta ambos casos con su ``field_path``.
    """
    return CronTrigger.from_crontab(schedule, timezone=ZoneInfo(timezone))


def next_fire_times(trigger: CronTrigger, now: datetime, count: int) -> list[datetime]:
    """Próximos ``count`` disparos de ``trigger`` a partir de ``now`` (inclusive).

    ``now`` debe ser tz-aware (el resultado se expresa en la timezone del
    trigger). El primer cálculo usa ``previous=None`` para no perder un disparo
    que coincida exactamente con ``now``; la lista puede ser más corta que
    ``count`` si el trigger no tiene más disparos (p. ej. la fecha imposible
    ``0 0 31 2 *`` devuelve una lista vacía). Es determinista: no consulta el
    reloj del sistema.
    """
    fires: list[datetime] = []
    previous: datetime | None = None
    for _ in range(count):
        # El segundo argumento es el ``now`` de la búsqueda: la primera vez es
        # el pedido por el usuario; en las siguientes, el disparo anterior (así
        # APScheduler busca *estrictamente* después de él y no repite el mismo
        # resultado cuando ``previous`` cae en el futuro respecto de ``now``).
        reference = now if previous is None else previous
        upcoming = trigger.get_next_fire_time(previous, reference)
        if upcoming is None:
            break
        fires.append(upcoming)
        previous = upcoming
    return fires


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """Desenlace de un ciclo del scheduler para un job.

    ``job_databases`` son las bases solicitadas por el job; ``databases`` las
    que el runner realmente ejecutó (vacío si el ciclo se omitió). ``skipped``
    con ``skipped_reason`` describen una omisión (solapamiento de bases o
    misfire, Item 051) y **tienen precedencia** sobre ``success`` en los
    consumidores del resultado (Item 052). ``success``/``partial`` describen el
    lote ejecutado: ``partial`` marca la mezcla de bases exitosas y fallidas
    (Item 054) y ``status`` lo traduce a ``CycleStatus`` sin agregar un campo
    más a la igualdad del dataclass. ``error_message`` resume el ciclo —incluida
    una excepción imprevista del runner, que el servicio convierte en un
    resultado fallido—; ``notification_sent`` registra si el correo del ciclo
    salió.
    """

    job_databases: tuple[str, ...]
    databases: tuple[str, ...] = ()
    skipped: bool = False
    skipped_reason: str | None = None
    success: bool = False
    duration_seconds: float = 0.0
    notification_sent: bool = False
    error_message: str | None = None
    partial: bool = False

    @property
    def status(self) -> CycleStatus:
        """Estado global del ciclo para el estado del servicio (Item 052)."""
        if self.skipped:
            return CycleStatus.SKIPPED
        if self.partial:
            return CycleStatus.PARTIAL
        return CycleStatus.SUCCESS if self.success else CycleStatus.FAILURE


class CycleStatus(StrEnum):
    """Estado global de un ciclo del scheduler (``scheduler_state.json``)."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    SKIPPED = "skipped"



@dataclass(frozen=True, slots=True)
class Reservation:
    """Reserva atómica de bases de un ciclo: tomadas y ya ocupadas por otro."""

    reserved: tuple[str, ...]
    busy: tuple[str, ...]


class InFlightRegistry:
    """Registro en proceso de las bases con un ciclo en ejecución (thread-safe).

    El lock protege el conjunto completo: la reserva de un subconjunto es
    atómica, así dos jobs que comparten una base no pueden tomarla a la vez.
    ``all_or_nothing`` implementa las dos semánticas de ``skip_if_running``:
    todo el job o nada (``True``) o solo las bases libres (``False``).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()

    def reserve(self, databases: Sequence[str], *, all_or_nothing: bool) -> Reservation:
        """Reserva ``databases`` (sin duplicados, preservando orden)."""
        requested = tuple(dict.fromkeys(databases))
        with self._lock:
            busy = tuple(name for name in requested if name in self._in_flight)
            if busy and all_or_nothing:
                return Reservation(reserved=(), busy=busy)
            reserved = tuple(name for name in requested if name not in self._in_flight)
            self._in_flight.update(reserved)
            return Reservation(reserved=reserved, busy=busy)

    def release(self, databases: Sequence[str]) -> None:
        """Libera ``databases`` (idempotente: liberar una libre no falla)."""
        with self._lock:
            for name in databases:
                self._in_flight.discard(name)

    def busy(self) -> frozenset[str]:
        """Bases en vuelo en este momento (copia inmutable)."""
        with self._lock:
            return frozenset(self._in_flight)


# --- estado consultable del servicio (Item 052) ---


@dataclass(frozen=True, slots=True)
class CycleRecord:
    """Último ciclo ejecutado por un job, tal como se persiste en el estado.

    ``databases`` son las bases realmente ejecutadas (vacío en una omisión),
    ``finished_at``/``duration_seconds`` ubican y miden la corrida, ``status``
    es el estado global (``CycleStatus``), ``notification_sent`` indica si el
    correo del ciclo salió y ``error_message`` el resumen de fallos ya
    enmascarado (sin secretos).
    """

    job_id: str
    databases: tuple[str, ...]
    finished_at: datetime
    duration_seconds: float
    status: CycleStatus
    notification_sent: bool = False
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class JobState:
    """Estado persistido de un job: horario, bases, próximo disparo y último ciclo."""

    job_id: str
    schedule: str
    databases: tuple[str, ...]
    next_fire_time: datetime | None = None
    last_cycle: CycleRecord | None = None


@dataclass(frozen=True, slots=True)
class ServiceState:
    """Estado completo del servicio persistido en ``work_dir/scheduler_state.json``.

    ``version`` es el esquema del archivo (``SCHEMA_VERSION``); ``pid`` el
    proceso que lo escribió (para detectar estado obsoleto); ``started_at``/
    ``updated_at`` acotan la corrida; ``jobs`` va en orden de registro y
    ``recent_errors`` es una ventana acotada de los últimos fallos.
    """

    version: int
    pid: int
    config_path: str
    started_at: datetime
    updated_at: datetime
    jobs: tuple[JobState, ...] = ()
    recent_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StateLoadResult:
    """Resultado tipado de ``load_state``: estado, vigencia y advertencia.

    ``state`` es ``None`` cuando el archivo no existe o no se pudo interpretar
    (``warning`` explica por qué); ``stale`` marca un estado cuyo ``pid`` ya no
    está vivo. Nunca representa una excepción: la lectura del estado es
    tolerante por contrato (Item 052).
    """

    state: ServiceState | None
    path: Path
    stale: bool = False
    warning: str | None = None


def state_path(work_dir: Path) -> Path:
    """Ruta del archivo de estado del servicio dentro de ``local.work_dir``."""
    return work_dir / STATE_FILENAME


def reload_request_path(work_dir: Path) -> Path:
    """Ruta del archivo de control de recarga dentro de ``local.work_dir``.

    La CLI lo crea en las plataformas sin ``SIGUSR1`` (Item 055) y el job
    ``reload-watcher`` del servicio lo detecta y lo consume.
    """
    return work_dir / RELOAD_REQUEST_FILENAME


def pid_is_alive(pid: int) -> bool:
    """Indica si ``pid`` corresponde a un proceso vivo.

    En POSIX usa ``os.kill(pid, 0)``: ``ProcessLookupError`` es un proceso
    muerto y ``PermissionError`` un proceso vivo de otro usuario. En Windows no
    hay comprobación barata y confiable sin abrir el proceso, así que se
    reporta vivo (el estado muestra el pid sin verificar). Un ``pid`` no
    positivo nunca es válido.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_str(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"campo '{field}': se esperaba un texto")
    return value


def _parse_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"campo '{field}': se esperaba un entero")
    return value


def _parse_float(data: dict[str, Any], field: str) -> float:
    value = data.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"campo '{field}': se esperaba un número")
    return float(value)


def _parse_datetime(data: dict[str, Any], field: str) -> datetime:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"campo '{field}': se esperaba una fecha ISO 8601")
    return datetime.fromisoformat(value)


def _parse_optional_datetime(data: dict[str, Any], field: str) -> datetime | None:
    if data.get(field) is None:
        return None
    return _parse_datetime(data, field)


def _cycle_record_to_dict(record: CycleRecord) -> dict[str, Any]:
    return {
        "job_id": record.job_id,
        "databases": list(record.databases),
        "finished_at": record.finished_at.isoformat(),
        "duration_seconds": record.duration_seconds,
        "status": record.status.value,
        "notification_sent": record.notification_sent,
        "error_message": record.error_message,
    }


def _job_state_to_dict(job: JobState) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "schedule": job.schedule,
        "databases": list(job.databases),
        "next_fire_time": (
            job.next_fire_time.isoformat() if job.next_fire_time is not None else None
        ),
        "last_cycle": (
            _cycle_record_to_dict(job.last_cycle) if job.last_cycle is not None else None
        ),
    }


def _state_to_dict(state: ServiceState) -> dict[str, Any]:
    return {
        "version": state.version,
        "pid": state.pid,
        "config_path": state.config_path,
        "started_at": state.started_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "jobs": [_job_state_to_dict(job) for job in state.jobs],
        "recent_errors": list(state.recent_errors),
    }


def _cycle_record_from_dict(data: object) -> CycleRecord:
    if not isinstance(data, dict):
        raise ValueError("campo 'last_cycle': se esperaba un objeto")
    databases = data.get("databases")
    if not isinstance(databases, list) or not all(isinstance(name, str) for name in databases):
        raise ValueError("campo 'last_cycle.databases': se esperaba una lista de textos")
    error_message = data.get("error_message")
    if error_message is not None and not isinstance(error_message, str):
        raise ValueError("campo 'last_cycle.error_message': se esperaba un texto o null")
    try:
        status = CycleStatus(_parse_str(data, "status"))
    except ValueError as exc:
        raise ValueError(f"campo 'last_cycle.status': {exc}") from exc
    return CycleRecord(
        job_id=_parse_str(data, "job_id"),
        databases=tuple(databases),
        finished_at=_parse_datetime(data, "finished_at"),
        duration_seconds=_parse_float(data, "duration_seconds"),
        status=status,
        notification_sent=bool(data.get("notification_sent", False)),
        error_message=error_message,
    )


def _job_state_from_dict(data: object) -> JobState:
    if not isinstance(data, dict):
        raise ValueError("campo 'jobs': se esperaba una lista de objetos")
    databases = data.get("databases")
    if not isinstance(databases, list) or not all(isinstance(name, str) for name in databases):
        raise ValueError("campo 'jobs[].databases': se esperaba una lista de textos")
    last_cycle = data.get("last_cycle")
    return JobState(
        job_id=_parse_str(data, "job_id"),
        schedule=_parse_str(data, "schedule"),
        databases=tuple(databases),
        next_fire_time=_parse_optional_datetime(data, "next_fire_time"),
        last_cycle=(
            _cycle_record_from_dict(last_cycle) if last_cycle is not None else None
        ),
    )


def _state_from_dict(data: object) -> ServiceState:
    """Reconstruye ``ServiceState`` validando el esquema; lanza ``ValueError``."""
    if not isinstance(data, dict):
        raise ValueError("el estado debe ser un objeto JSON")
    version = data.get("version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"esquema desconocido: versión {version!r} (se esperaba {SCHEMA_VERSION})"
        )
    jobs_raw = data.get("jobs", [])
    if not isinstance(jobs_raw, list):
        raise ValueError("campo 'jobs': se esperaba una lista")
    errors_raw = data.get("recent_errors", [])
    if not isinstance(errors_raw, list) or not all(isinstance(item, str) for item in errors_raw):
        raise ValueError("campo 'recent_errors': se esperaba una lista de textos")
    return ServiceState(
        version=version,
        pid=_parse_int(data, "pid"),
        config_path=_parse_str(data, "config_path"),
        started_at=_parse_datetime(data, "started_at"),
        updated_at=_parse_datetime(data, "updated_at"),
        jobs=tuple(_job_state_from_dict(item) for item in jobs_raw),
        recent_errors=tuple(errors_raw),
    )


def write_state(path: Path, state: ServiceState) -> None:
    """Persiste ``state`` de forma atómica (``tempfile`` + ``os.replace``).

    El JSON se escribe completo en un temporal del mismo directorio, se
    sincroniza a disco y recién ahí reemplaza al archivo definitivo: un lector
    concurrente nunca ve un archivo a medio escribir y un fallo deja intacto el
    estado previo. Ante cualquier error se elimina el temporal antes de
    propagar (la escritura del estado no debe dejar basura en ``work_dir``).
    """
    payload = json.dumps(_state_to_dict(state), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def load_state(path: Path) -> StateLoadResult:
    """Lee el estado de ``path`` sin lanzar nunca (Item 052).

    Archivo ausente, JSON corrupto, tipos inesperados o ``version`` distinta de
    ``SCHEMA_VERSION`` devuelven ``state=None`` con ``warning``. Con un estado
    legible, ``stale`` indica que el ``pid`` que lo escribió ya no vive.
    """
    if not path.exists():
        return StateLoadResult(None, path, warning=f"no existe el archivo de estado: {path}")
    try:
        state = _state_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return StateLoadResult(
            None, path, warning=f"estado ilegible ({type(exc).__name__}): {exc}"
        )
    return StateLoadResult(state, path, stale=not pid_is_alive(state.pid))


class SchedulerStateStore:
    """Acumulador thread-safe del estado del servicio (Item 052).

    El servicio registra sus jobs al arrancar y cada ``run_job`` registra el
    desenlace (éxito, parcial, fallo u omisión) con el próximo disparo; el
    ``save()`` persiste un snapshot atómico. ``mask`` enmascara los mensajes
    antes de guardarlos —el contrato del estado es no contener secretos— y
    ``max_recent_errors`` acota la ventana de errores. El lock serializa las
    mutaciones, los snapshots y las escrituras: dos jobs concurrentes no
    corrompen el archivo ni pierden el último desenlace.
    """

    def __init__(
        self,
        path: Path,
        *,
        pid: int,
        config_path: str,
        started_at: datetime,
        mask: Callable[[str], str] | None = None,
        max_recent_errors: int = MAX_RECENT_ERRORS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path
        self._pid = pid
        self._config_path = config_path
        self._started_at = started_at
        self._mask: Callable[[str], str] = mask or (lambda text: text)
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}
        self._recent_errors: deque[str] = deque(maxlen=max(1, max_recent_errors))

    @property
    def path(self) -> Path:
        """Ruta del archivo de estado que administra el store."""
        return self._path

    def register_job(
        self,
        job_id: str,
        job: SchedulerJob,
        *,
        next_fire_time: datetime | None = None,
    ) -> None:
        """Registra (o actualiza) un job preservando su último ciclo."""
        with self._lock:
            previous = self._jobs.get(job_id)
            self._jobs[job_id] = JobState(
                job_id=job_id,
                schedule=job.schedule,
                databases=tuple(job.databases),
                next_fire_time=next_fire_time,
                last_cycle=previous.last_cycle if previous is not None else None,
            )

    def record_cycle(
        self,
        job_id: str,
        outcome: CycleOutcome,
        *,
        next_fire_time: datetime | None = None,
    ) -> CycleRecord:
        """Registra el desenlace de un ciclo y acumula su error si falló.

        Los estados ``partial``/``failure`` entran en ``recent_errors`` como una
        línea ``job: estado: motivo`` (el motivo enmascarado); un
        ``error_message`` suelto también se acumula. Una omisión (``skipped``)
        solo actualiza el último ciclo.
        """
        error_message = (
            self._mask(outcome.error_message) if outcome.error_message is not None else None
        )
        record = CycleRecord(
            job_id=job_id,
            databases=tuple(outcome.databases),
            finished_at=self._clock(),
            duration_seconds=outcome.duration_seconds,
            status=outcome.status,
            notification_sent=outcome.notification_sent,
            error_message=error_message,
        )
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                current = JobState(
                    job_id=job_id,
                    schedule="",
                    databases=tuple(outcome.job_databases),
                )
            self._jobs[job_id] = replace(
                current, next_fire_time=next_fire_time, last_cycle=record
            )
            if outcome.status in (CycleStatus.PARTIAL, CycleStatus.FAILURE):
                detail = error_message or "ciclo fallido sin detalle"
                self._recent_errors.append(f"{job_id}: {outcome.status.value}: {detail}")
            elif error_message is not None:
                self._recent_errors.append(error_message)
        return record

    def record_error(self, message: str) -> None:
        """Acumula un error general (enmascarado) en la ventana de recientes."""
        masked = self._mask(message)
        with self._lock:
            self._recent_errors.append(masked)

    def remove_job(self, job_id: str) -> None:
        """Elimina el estado de un job (p. ej. tras una recarga que lo quitó)."""
        with self._lock:
            self._jobs.pop(job_id, None)

    def set_mask(self, mask: Callable[[str], str]) -> None:
        """Reemplaza el enmascarador (recarga en caliente con secretos nuevos).

        El servicio lo llama al aplicar una configuración nueva para que los
        ``error_message`` que se persistan a partir de ese momento se enmascaren
        con los secretos vigentes y no con los de la configuración anterior.
        """
        with self._lock:
            self._mask = mask

    def _snapshot_locked(self) -> ServiceState:
        return ServiceState(
            version=SCHEMA_VERSION,
            pid=self._pid,
            config_path=self._config_path,
            started_at=self._started_at,
            updated_at=self._clock(),
            jobs=tuple(self._jobs.values()),
            recent_errors=tuple(self._recent_errors),
        )

    def snapshot(self) -> ServiceState:
        """Estado actual (inmutable) con la marca de tiempo del reloj del store."""
        with self._lock:
            return self._snapshot_locked()

    def save(self) -> Path:
        """Persiste un snapshot atómico y devuelve la ruta del archivo."""
        with self._lock:
            write_state(self._path, self._snapshot_locked())
        return self._path


def render_service_status(result: StateLoadResult) -> str:
    """Renderiza el estado del servicio para ``odin service status`` (Item 053).

    Sin estado legible explica la causa; con estado, la cabecera distingue
    "en ejecución" (pid vivo) de "detenido" (estado obsoleto de un proceso que
    ya no corre) y detalla config, marca de tiempo, salud, cada job con su
    próximo disparo y último ciclo, y los errores recientes. Es solo
    presentación: nunca resuelve la vigencia por su cuenta (lo hace
    ``load_state``).
    """
    if result.state is None:
        return "\n".join(
            [
                "Servicio ODIN: sin estado",
                f"Ruta: {result.path}",
                f"Motivo: {result.warning}",
            ]
        )
    state = result.state
    if result.stale:
        header = f"Servicio ODIN: detenido (pid {state.pid} ya no está en ejecución)"
    else:
        header = f"Servicio ODIN: en ejecución (pid {state.pid})"
    health = "OK"
    if state.recent_errors:
        health = f"DEGRADADA ({len(state.recent_errors)} error(es) reciente(s))"
    lines = [
        header,
        f"Config: {state.config_path}",
        f"Iniciado: {state.started_at.isoformat()}",
        f"Última actualización: {state.updated_at.isoformat()}",
        f"Salud: {health}",
        f"Jobs ({len(state.jobs)}):",
    ]
    for job in state.jobs:
        next_fire = "sin próximo disparo"
        if job.next_fire_time is not None:
            next_fire = job.next_fire_time.isoformat()
        lines.append(
            f"- {job.job_id} [{', '.join(job.databases)}] schedule '{job.schedule}'"
        )
        lines.append(f"  Próximo disparo: {next_fire}")
        last_cycle = job.last_cycle
        if last_cycle is None:
            lines.append("  Último ciclo: sin ejecuciones registradas")
            continue
        databases = ", ".join(last_cycle.databases) or "ninguna"
        mail = "correo enviado" if last_cycle.notification_sent else "correo NO enviado"
        detail = (
            f"  Último ciclo: {last_cycle.status.value} en "
            f"{last_cycle.duration_seconds:.1f} s ({databases}; {mail})"
        )
        if last_cycle.error_message:
            detail += f" — {last_cycle.error_message}"
        lines.append(detail)
    if state.recent_errors:
        lines.append(f"Errores recientes ({len(state.recent_errors)}):")
        lines.extend(f"- {error}" for error in state.recent_errors)
    return "\n".join(lines)


# --- runner real del ciclo sobre el pipeline (Item 054) ---


def _failure_detail(result: BackupResult) -> str:
    """Motivo más específico de una base fallida (compresión > transferencia > respaldo)."""
    return (
        result.compression_error_message
        or result.transfer_error_message
        or result.error_message
        or "fallo sin detalle"
    )


def _outcome_from_pipeline(
    job: SchedulerJob, result: PipelineResult, duration_seconds: float
) -> CycleOutcome:
    """Traduce el ``PipelineResult`` del ciclo a ``CycleOutcome`` (Item 054).

    Prioridad de estados: lote no ejecutado (``error_message``) o vacío →
    ``FAILURE``; mezcla de bases exitosas y fallidas → ``PARTIAL``; todo
    exitoso → ``SUCCESS``; ninguna exitosa → ``FAILURE``. El ``error_message``
    del ciclo resume las bases fallidas con su motivo más específico.
    """
    batch = result.backup
    results = batch.results
    notification = result.notification
    notification_sent = bool(notification is not None and notification.success)
    executed = tuple(item.database_name for item in results)
    if batch.error_message is not None:
        status = CycleStatus.FAILURE
        error_message = batch.error_message
    elif not results:
        status = CycleStatus.FAILURE
        if job.databases:
            error_message = (
                "lote vacío: ninguna de las bases del job ("
                + ", ".join(job.databases)
                + ") está en la configuración"
            )
        else:
            error_message = "el job no define bases"
    else:
        failed = [item for item in results if not item.success]
        if failed:
            status = (
                CycleStatus.PARTIAL if len(failed) < len(results) else CycleStatus.FAILURE
            )
            error_message = "; ".join(
                f"{item.database_name}: {_failure_detail(item)}" for item in failed
            )
        else:
            status = CycleStatus.SUCCESS
            error_message = None
    return CycleOutcome(
        job_databases=tuple(job.databases),
        databases=executed,
        success=status is CycleStatus.SUCCESS,
        partial=status is CycleStatus.PARTIAL,
        duration_seconds=duration_seconds,
        notification_sent=notification_sent,
        error_message=error_message,
    )


class PipelineCycleRunner:
    """``cycle_runner`` real: pipeline completo por subconjunto de bases (Item 054).

    Filtra ``config.databases`` por las bases del job efectivo (el que el
    Item 051 ya acotó según ``skip_if_running``), construye la configuración
    del ciclo con ``dataclasses.replace`` —la del servicio queda intacta— e
    invoca ``run_pipeline`` con su propio correo por ciclo y su retención. El
    resultado se traduce a ``CycleOutcome`` (estado global, bases ejecutadas,
    duración, correo y resumen de fallos).

    ``run`` y las opciones del pipeline son inyectables: los tests usan un
    doble sin red/SMTP y la integración (Item 056) inyecta fases dobles. Un
    fallo inesperado del pipeline no se encapsula acá: lo aísla
    ``SchedulerService.run_job``, que además libera las reservas y persiste el
    estado.
    """

    def __init__(self, run: Callable[..., PipelineResult] = run_pipeline, **options: Any) -> None:
        self._run = run
        self._options = options

    def __call__(self, config: Config, job: SchedulerJob) -> CycleOutcome:
        requested = set(job.databases)
        selected = [database for database in config.databases if database.name in requested]
        started = time.monotonic()
        result = self._run(replace(config, databases=selected), **self._options)
        outcome = _outcome_from_pipeline(job, result, time.monotonic() - started)
        if outcome.status is CycleStatus.SUCCESS:
            logger.info(
                "Ciclo ejecutado: %s bases=%s (%.1f s, correo %s)",
                outcome.status.value,
                ", ".join(outcome.databases) or "ninguna",
                outcome.duration_seconds,
                "enviado" if outcome.notification_sent else "no enviado",
            )
        else:
            logger.warning(
                "Ciclo con estado '%s' (bases=%s): %s",
                outcome.status.value,
                ", ".join(outcome.databases) or "ninguna",
                outcome.error_message,
            )
        return outcome


class SchedulerService:
    """Servicio de scheduling en primer plano sobre ``BlockingScheduler``.

    Registra un job APScheduler por entrada de ``config.scheduler.jobs`` con id
    estable ``job-N`` (índice en la lista), ``max_instances=1`` y
    ``replace_existing=True``. ``start()`` bloquea hasta ``shutdown()``.

    ``cycle_runner`` es la interfaz con el pipeline: recibe la ``Config``
    completa y el ``SchedulerJob`` del disparo y devuelve un ``CycleOutcome``.
    Los últimos desenlaces quedan en ``last_outcomes`` por id de job. El reloj
    (``now``) es inyectable para tests deterministas.

    La recarga en caliente (Item 055) se pide con ``request_reload()`` (usada
    por el manejador de ``SIGUSR1``) o dejando ``scheduler_reload.request`` en
    ``local.work_dir``; el job interno ``reload-watcher`` llama a
    ``process_reload()`` periódicamente. ``on_config_reloaded`` es el hook
    (opcional) que la CLI usa para renovar el logging al aplicar una config.
    """

    def __init__(
        self,
        config: Config,
        *,
        cycle_runner: CycleRunner,
        scheduler: BlockingScheduler | None = None,
        now: Clock | None = None,
        in_flight: InFlightRegistry | None = None,
        state_store: SchedulerStateStore | None = None,
        on_config_reloaded: Callable[[Config], None] | None = None,
    ) -> None:
        self.config = config
        self._cycle_runner = cycle_runner
        self._timezone = ZoneInfo(config.scheduler.timezone)
        self._now_override = now
        self._now: Clock = now or (lambda: datetime.now(self._timezone))
        self._scheduler = scheduler or BlockingScheduler(timezone=self._timezone)
        self._in_flight = in_flight or InFlightRegistry()
        self._state_store = state_store
        self._on_config_reloaded = on_config_reloaded
        self._jobs: dict[str, SchedulerJob] = {}
        self._triggers: dict[str, CronTrigger] = {}
        self._expected_fires: dict[str, datetime | None] = {}
        self._reload_requested = threading.Event()
        self._reload_lock = threading.Lock()
        self._reload_path = reload_request_path(config.local.work_dir)
        self.last_outcomes: dict[str, CycleOutcome] = {}
        self._register_jobs()
        self._register_reload_watcher()

    @property
    def scheduler(self) -> BlockingScheduler:
        """Scheduler subyacente (para inspección de jobs y pruebas)."""
        return self._scheduler

    @property
    def timezone(self) -> ZoneInfo:
        """Timezone global del JSON con la que corre el servicio."""
        return self._timezone

    def _register_jobs(self) -> None:
        """Registra (o reemplaza) los jobs del bloque ``scheduler`` del JSON.

        Políticas de misfire (Item 051): ``coalesce=True`` siempre (varios
        disparos vencidos se colapsan en uno) y ``misfire_grace_time`` acotado
        por política — ``None`` para ``run_once`` (la corrida recuperada se
        ejecuta aunque llegue tarde) y ``_MISFIRE_TOLERANCE_SEC`` para ``skip``
        (los disparos vencidos los descarta APScheduler y, además, el guard de
        latencia de ``run_job`` usa el reloj inyectable).

        Un job existente con el mismo id se elimina antes de agregarlo: con el
        scheduler detenido ``replace_existing`` no reemplaza a los jobs
        pendientes de la recarga (quedarían duplicados y ``get_job`` devolvería
        el viejo), así que la re-registración en caliente lo hace explícito.
        """
        for index, job in enumerate(self.config.scheduler.jobs):
            job_id = f"job-{index}"
            if self._scheduler.get_job(job_id) is not None:
                self._scheduler.remove_job(job_id)
            trigger = cron_trigger(job.schedule, self.config.scheduler.timezone)
            run_once = job.on_misfire is MisfirePolicy.RUN_ONCE
            next_fire = trigger.get_next_fire_time(None, self._now())
            self._scheduler.add_job(
                self.run_job,
                trigger=trigger,
                args=(job_id,),
                id=job_id,
                name=job_id,
                max_instances=1,
                replace_existing=True,
                coalesce=True,
                misfire_grace_time=None if run_once else _MISFIRE_TOLERANCE_SEC,
                next_run_time=next_fire,
            )
            self._jobs[job_id] = job
            self._triggers[job_id] = trigger
            self._expected_fires[job_id] = next_fire
            if self._state_store is not None:
                self._state_store.register_job(job_id, job, next_fire_time=next_fire)
            logger.info(
                "Job '%s' registrado: schedule '%s' en %s, bases: %s (misfire: %s)",
                job_id,
                job.schedule,
                self.config.scheduler.timezone,
                ", ".join(job.databases),
                job.on_misfire.value,
            )

    def job_config(self, job_id: str) -> SchedulerJob:
        """Configuración del job registrado (``KeyError`` si no existe)."""
        return self._jobs[job_id]

    # --- recarga en caliente (Item 055) ---

    def _register_reload_watcher(self) -> None:
        """Registra el job interno que procesa las recargas pendientes.

        ``IntervalTrigger`` cada ``RELOAD_POLL_SECONDS`` (con la timezone
        vigente), ``max_instances=1`` y ``replace_existing``: se re-registra al
        aplicar una configuración nueva sin duplicarse. No aparece en
        ``self._jobs`` ni en el estado —no es un job de la configuración—.
        """
        self._scheduler.add_job(
            self.process_reload,
            trigger=IntervalTrigger(seconds=RELOAD_POLL_SECONDS, timezone=self._timezone),
            id=RELOAD_WATCHER_JOB_ID,
            name=RELOAD_WATCHER_JOB_ID,
            max_instances=1,
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=int(RELOAD_POLL_SECONDS),
        )

    @property
    def reload_request_path(self) -> Path:
        """Ruta del archivo de control de recarga que vigila el servicio."""
        return self._reload_path

    def request_reload(self) -> None:
        """Marca una recarga pendiente (thread-safe).

        Es la única operación que ejecuta el manejador de ``SIGUSR1``: solo
        activa un ``threading.Event``, sin tocar el scheduler desde el contexto
        de la señal. El job ``reload-watcher`` la procesa poco después.
        """
        self._reload_requested.set()

    def reload_pending(self) -> bool:
        """Indica si hay una recarga pendiente (bandera o archivo de control)."""
        return self._reload_requested.is_set() or self._reload_path.exists()

    def _consume_reload_request(self) -> None:
        """Limpia la bandera y elimina el archivo de control (idempotente)."""
        self._reload_requested.clear()
        with contextlib.suppress(OSError):
            self._reload_path.unlink()

    def _reject_reload(self, reason: str) -> None:
        """Conserva la configuración vigente y registra el motivo (log + estado)."""
        message = f"recarga de configuración rechazada: {reason}"
        logger.error("%s", message)
        if self._state_store is not None:
            self._state_store.record_error(message)
            self._state_store.save()

    def process_reload(self) -> bool:
        """Procesa una recarga pendiente; ``True`` si aplicó una config válida.

        Consume la solicitud (bandera + archivo de control) y valida la
        configuración editada en ``config.config_path`` con ``load_config``
        (estructura/semántica) y ``validate_config`` (entorno y coherencia,
        importado en forma diferida porque ``odin.validate`` importa este
        módulo). Si es válida, ``_apply_config`` la aplica en caliente y llama
        al hook ``on_config_reloaded``; si no, ``_reject_reload`` deja el
        servicio con la configuración vigente y el motivo en el log y en el
        estado. Un lock serializa los procesamientos (el watcher y una llamada
        directa no se pisan).
        """
        with self._reload_lock:
            if not self.reload_pending():
                return False
            self._consume_reload_request()
            try:
                new_config = load_config(self.config.config_path)
            except ConfigError as exc:
                self._reject_reload(str(exc))
                return False
            from odin.validate import validate_config

            report = validate_config(new_config)
            if not report.is_valid(strict=False):
                detail = "; ".join(
                    f"{finding.field_path}: {finding.message}"
                    for finding in report.errors
                )
                self._reject_reload(f"configuración inválida: {detail}")
                return False
            self._apply_config(new_config)
            logger.info(
                "Configuración recargada en caliente: %d job(s) en %s (%s)",
                len(new_config.scheduler.jobs),
                new_config.scheduler.timezone,
                new_config.config_path,
            )
            return True

    def _apply_config(self, config: Config) -> None:
        """Aplica ``config`` sin reiniciar: timezone, jobs, estado y máscara.

        Los jobs que ya no existen se eliminan del scheduler y del estado; los
        vigentes se re-registran con ``replace_existing`` (trigger y próximo
        disparo nuevos). La máscara del ``SchedulerStateStore`` se refresca con
        los secretos de la configuración nueva y el hook ``on_config_reloaded``
        permite a la CLI renovar el logging (``setup_logging`` es idempotente).
        """
        previous_ids = set(self._jobs)
        self.config = config
        self._timezone = ZoneInfo(config.scheduler.timezone)
        if self._now_override is None:
            self._now = lambda: datetime.now(self._timezone)
        self._scheduler.timezone = self._timezone
        self._reload_path = reload_request_path(config.local.work_dir)
        current_ids = {f"job-{index}" for index in range(len(config.scheduler.jobs))}
        for job_id in previous_ids - current_ids:
            if self._scheduler.get_job(job_id) is not None:
                self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            self._triggers.pop(job_id, None)
            self._expected_fires.pop(job_id, None)
            if self._state_store is not None:
                self._state_store.remove_job(job_id)
        self._register_jobs()
        self._register_reload_watcher()
        if self._state_store is not None:
            self._state_store.set_mask(SecretMasker.from_config(config).mask)
            self._state_store.save()
        if self._on_config_reloaded is not None:
            self._on_config_reloaded(config)

    def _skip(self, job_id: str, reason: str) -> CycleOutcome:
        """Registra y devuelve la omisión de un ciclo (log + ``CycleOutcome``)."""
        job = self._jobs[job_id]
        outcome = CycleOutcome(
            job_databases=tuple(job.databases),
            skipped=True,
            skipped_reason=reason,
        )
        logger.warning("Job '%s' omitido: %s", job_id, reason)
        return outcome

    def _complete(self, job_id: str, outcome: CycleOutcome) -> CycleOutcome:
        """Cierra un ciclo: estado persistido (si hay store) y ``last_outcomes``."""
        if self._state_store is not None:
            self._state_store.record_cycle(
                job_id, outcome, next_fire_time=self._next_fire_time(job_id)
            )
            self._state_store.save()
        self.last_outcomes[job_id] = outcome
        return outcome

    def _next_fire_time(self, job_id: str) -> datetime | None:
        """Próximo disparo del job: el programado por APScheduler o el esperado.

        Con el scheduler corriendo ``Job.next_run_time`` es autoritativo (lo
        actualiza APScheduler tras cada disparo); en frío se usa el cálculo del
        registro/misfire. ``None`` cuando el trigger no tiene más disparos.
        """
        registered = self._scheduler.get_job(job_id)
        if registered is not None:
            next_run: datetime | None = registered.next_run_time
            if next_run is not None:
                return next_run
        return self._expected_fires.get(job_id)

    def run_job(self, job_id: str) -> CycleOutcome:
        """Ejecuta el ciclo de ``job_id`` y registra su desenlace.

        Lo invoca APScheduler en el hilo del executor; también es la entrada
        determinista de los tests (sin esperar al reloj). Antes de correr:

        - **Misfire** (Item 051): con ``on_misfire=skip`` un disparo que llega
          más de ``_MISFIRE_TOLERANCE_SEC`` tarde respecto del próximo disparo
          esperado del trigger se descarta.
        - **Solapamiento** (Item 051): se reservan las bases del job en el
          ``InFlightRegistry``; con ``skip_if_running=true`` el ciclo se omite
          si alguna base está en vuelo, con ``false`` corre solo con las libres
          (nunca se duplica una base). Las reservas se liberan siempre al
          terminar, incluso si el runner lanza.

        Un fallo inesperado del ``cycle_runner`` no escapa: se convierte en un
        ``CycleOutcome`` fallido y el servicio sigue operativo. Un disparo
        encolado de un job que la recarga en caliente acaba de eliminar se
        descarta como omisión, sin registrar un ciclo de un job inexistente.
        """
        job = self._jobs.get(job_id)
        if job is None:
            logger.warning(
                "Job '%s' ya no existe (configuración recargada): ciclo descartado",
                job_id,
            )
            return CycleOutcome(
                job_databases=(),
                skipped=True,
                skipped_reason="job eliminado por la recarga de configuración",
            )
        now = self._now()
        expected = self._expected_fires.get(job_id)
        if expected is not None:
            self._expected_fires[job_id] = self._triggers[job_id].get_next_fire_time(
                expected, now
            )
        if (
            job.on_misfire is MisfirePolicy.SKIP
            and expected is not None
            and (now - expected).total_seconds() > _MISFIRE_TOLERANCE_SEC
        ):
            late = (now - expected).total_seconds()
            return self._complete(
                job_id,
                self._skip(
                    job_id,
                    f"disparo vencido hace {late:.0f} s (tolerancia "
                    f"{_MISFIRE_TOLERANCE_SEC:.0f} s, on_misfire=skip)",
                ),
            )
        reservation = self._in_flight.reserve(
            job.databases, all_or_nothing=job.skip_if_running
        )
        if not reservation.reserved:
            return self._complete(
                job_id,
                self._skip(
                    job_id,
                    "bases en ejecución por otro job: " + ", ".join(reservation.busy),
                ),
            )
        if reservation.busy:
            logger.warning(
                "Job '%s': bases ocupadas omitidas en este ciclo: %s",
                job_id,
                ", ".join(reservation.busy),
            )
        effective_job = (
            job
            if set(reservation.reserved) == set(job.databases)
            else replace(job, databases=list(reservation.reserved))
        )
        started = time.monotonic()
        try:
            outcome = self._cycle_runner(self.config, effective_job)
        except Exception as exc:  # noqa: BLE001 - un ciclo no debe tumbar el servicio
            message = f"fallo inesperado del ciclo: {type(exc).__name__}: {exc}"
            logger.exception("Job '%s': %s", job_id, message)
            outcome = CycleOutcome(
                job_databases=tuple(job.databases),
                databases=reservation.reserved,
                success=False,
                duration_seconds=time.monotonic() - started,
                error_message=message,
            )
        else:
            outcome = replace(outcome, job_databases=tuple(job.databases))
            logger.info(
                "Job '%s' finalizado: success=%s bases=%s (%.1f s)",
                job_id,
                outcome.success,
                ", ".join(outcome.databases) or "ninguna",
                outcome.duration_seconds,
            )
        finally:
            self._in_flight.release(reservation.reserved)
        return self._complete(job_id, outcome)

    def start(self) -> None:
        """Arranca el scheduler y **bloquea** hasta ``shutdown()``.

        Un ciclo que falle no detiene el servicio: los errores se encapsulan en
        ``CycleOutcome`` (``run_job``). Con ``scheduler.jobs`` vacío el proceso
        queda a la espera sin disparar nada.
        """
        logger.info(
            "Scheduler iniciado: %d job(s) en %s",
            len(self._jobs),
            self.config.scheduler.timezone,
        )
        try:
            self._scheduler.start()
        finally:
            logger.info("Scheduler detenido")

    def shutdown(self, *, wait: bool = True) -> None:
        """Detiene el scheduler; no falla si no estaba corriendo (idempotente)."""
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=wait)
