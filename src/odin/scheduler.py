"""Scheduler interno de ODIN sobre APScheduler 3.x (Items 049-051).

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

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from odin.config import Config, MisfirePolicy, SchedulerJob

__all__ = [
    "CycleOutcome",
    "InFlightRegistry",
    "Reservation",
    "SchedulerService",
    "cron_trigger",
    "next_fire_times",
]

logger = logging.getLogger(__name__)

# Tolerancia de latencia de un disparo en segundos (Item 051): un job con
# on_misfire=skip que se ejecuta más tarde que esto se descarta; también es el
# ``misfire_grace_time`` configurado en APScheduler para esos jobs, que exige un
# entero positivo (o None).
_MISFIRE_TOLERANCE_SEC = 1

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
    consumidores del resultado (Item 052). ``success``/``error_message``
    resumen el ciclo ejecutado —incluida una excepción imprevista del runner,
    que el servicio convierte en un resultado fallido—; ``notification_sent``
    registra si el correo del ciclo salió.
    """

    job_databases: tuple[str, ...]
    databases: tuple[str, ...] = ()
    skipped: bool = False
    skipped_reason: str | None = None
    success: bool = False
    duration_seconds: float = 0.0
    notification_sent: bool = False
    error_message: str | None = None


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


class SchedulerService:
    """Servicio de scheduling en primer plano sobre ``BlockingScheduler``.

    Registra un job APScheduler por entrada de ``config.scheduler.jobs`` con id
    estable ``job-N`` (índice en la lista), ``max_instances=1`` y
    ``replace_existing=True``. ``start()`` bloquea hasta ``shutdown()``.

    ``cycle_runner`` es la interfaz con el pipeline: recibe la ``Config``
    completa y el ``SchedulerJob`` del disparo y devuelve un ``CycleOutcome``.
    Los últimos desenlaces quedan en ``last_outcomes`` por id de job. El reloj
    (``now``) es inyectable para tests deterministas.
    """

    def __init__(
        self,
        config: Config,
        *,
        cycle_runner: CycleRunner,
        scheduler: BlockingScheduler | None = None,
        now: Clock | None = None,
        in_flight: InFlightRegistry | None = None,
    ) -> None:
        self.config = config
        self._cycle_runner = cycle_runner
        self._timezone = ZoneInfo(config.scheduler.timezone)
        self._now: Clock = now or (lambda: datetime.now(self._timezone))
        self._scheduler = scheduler or BlockingScheduler(timezone=self._timezone)
        self._in_flight = in_flight or InFlightRegistry()
        self._jobs: dict[str, SchedulerJob] = {}
        self._triggers: dict[str, CronTrigger] = {}
        self._expected_fires: dict[str, datetime | None] = {}
        self.last_outcomes: dict[str, CycleOutcome] = {}
        self._register_jobs()

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
        """
        for index, job in enumerate(self.config.scheduler.jobs):
            job_id = f"job-{index}"
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

    def _skip(self, job_id: str, reason: str) -> CycleOutcome:
        """Registra y devuelve la omisión de un ciclo (log + ``CycleOutcome``)."""
        job = self._jobs[job_id]
        outcome = CycleOutcome(
            job_databases=tuple(job.databases),
            skipped=True,
            skipped_reason=reason,
        )
        logger.warning("Job '%s' omitido: %s", job_id, reason)
        self.last_outcomes[job_id] = outcome
        return outcome

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
        ``CycleOutcome`` fallido y el servicio sigue operativo.
        """
        job = self._jobs[job_id]
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
            return self._skip(
                job_id,
                f"disparo vencido hace {late:.0f} s (tolerancia "
                f"{_MISFIRE_TOLERANCE_SEC:.0f} s, on_misfire=skip)",
            )
        reservation = self._in_flight.reserve(
            job.databases, all_or_nothing=job.skip_if_running
        )
        if not reservation.reserved:
            return self._skip(
                job_id,
                "bases en ejecución por otro job: " + ", ".join(reservation.busy),
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
        self.last_outcomes[job_id] = outcome
        return outcome

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
