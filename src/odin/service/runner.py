"""Runner compartido del modo servicio de ODIN (Item 065).

``ServiceRunner`` es la pieza común entre ``odin service run`` en primer plano,
la unit systemd (``ExecStart=<odin> service run --config <ruta>``) y el
``SvcDoRun`` de Windows: carga y valida la configuración, arma el logging del
modo residente (sin consola y con ``sys.stdout``/``sys.stderr`` redirigidos al
log, Item 064), construye el ``SchedulerStateStore`` y el ``SchedulerService``
real (``PipelineCycleRunner`` y hook de recarga que re-configura el logging) y
expone el contrato ``ServiceRuntime`` del Item 059:

- ``run()``: bloqueante; persiste el estado inicial, arranca el scheduler y
  devuelve el exit code del CLI (0 cierre limpio, 2 configuración). En POSIX
  ``SIGINT``/``SIGTERM`` lo detienen con cierre limpio y ``SIGUSR1`` pide la
  recarga en caliente.
- ``stop()``: thread-safe e idempotente; lo invocan el hilo del SCM
  (``SvcStop``) o la señal del gestor. Detiene el scheduler, persiste el estado
  final y registra el cierre. Un ``stop()`` previo al arranque impide que el
  scheduler se inicie (la carrera arranque/parada del gestor no deja el proceso
  bloqueado).

``build_scheduler_service`` es la fábrica real del servicio que comparten el
runner y la CLI en primer plano (``console=True``): inyecta
``PipelineCycleRunner`` y el hook ``on_config_reloaded`` que re-aplica
``setup_logging`` (idempotente) en la misma modalidad de consola.

Los exit codes replican el contrato de ``odin.cli`` (0/1/2) sin importar el
módulo del CLI (la dependencia sería invertida); un test guarda la igualdad de
ambos conjuntos de constantes.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from typing import Any

from odin.config import Config, ConfigError, load_config
from odin.log import LOG_FILENAME, SecretMasker, redirect_stdio_to_log, setup_logging
from odin.scheduler import SchedulerService, SchedulerStateStore, state_path

__all__ = [
    "ENV_CONFIG_VAR",
    "EXIT_CONFIG",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "ServiceRunner",
    "build_scheduler_service",
]

logger = logging.getLogger(__name__)

# Mismo contrato de exit codes que ``odin.cli`` (documentado en su docstring):
# el runner no importa el CLI (dependencia invertida); un test guarda la
# igualdad para que ambos conjuntos no deriven.
EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_CONFIG = 2
ENV_CONFIG_VAR = "ODIN_CONFIG"

ServiceFactory = Callable[..., SchedulerService]


def _setup_logging_or_warn(config: Config, *, console: bool) -> Logger | None:
    """Configura el logging; si el destino no es operable, advierte y sigue.

    Misma postura que la CLI (criterio 6 del Item 005): un fallo operativo de
    logging (p. ej. ``OSError`` porque el directorio de logs no es creable) no
    invalida la configuración. Solo se captura ``OSError``: cualquier otra
    excepción es un error interno.
    """
    try:
        return setup_logging(config, console=console)
    except OSError as exc:
        print(
            f"Advertencia: no se pudo configurar el logging ({exc}); "
            "la configuración es válida pero esta ejecución no quedará registrada.",
            file=sys.stderr,
        )
        return None


def build_scheduler_service(
    config: Config, *, state_store: SchedulerStateStore, console: bool = False
) -> SchedulerService:
    """Fábrica real del servicio: ``PipelineCycleRunner`` y hook de recarga.

    El hook re-ejecuta ``setup_logging`` con la misma modalidad de consola
    cuando la recarga en caliente aplica una configuración válida (Item 055);
    ``setup_logging`` es idempotente, así que no duplica handlers.
    """
    from odin.scheduler import PipelineCycleRunner

    def on_config_reloaded(new_config: Config) -> None:
        _setup_logging_or_warn(new_config, console=console)

    return SchedulerService(
        config,
        cycle_runner=PipelineCycleRunner(),
        state_store=state_store,
        on_config_reloaded=on_config_reloaded,
    )


@contextmanager
def _stop_signals() -> Iterator[None]:
    """Instala ``SIGINT``/``SIGTERM`` para detener el servicio y restaura los previos.

    El handler levanta ``KeyboardInterrupt`` en el hilo principal —donde el
    ``BlockingScheduler`` está bloqueado— y ``ServiceRunner.run()`` lo traduce
    en un shutdown limpio con exit 0. Fuera del hilo principal (uso embebido en
    tests) no toca las señales globales, que solo el hilo principal puede
    configurar; un SO que rechace el handler simplemente conserva el previo.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _raise_interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    previous: dict[signal.Signals, Any] = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, _raise_interrupt)
        except (ValueError, OSError):
            continue
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextmanager
def _reload_signal(service: SchedulerService) -> Iterator[None]:
    """Instala ``SIGUSR1`` para pedir la recarga en caliente (Item 055).

    El handler solo llama a ``service.request_reload()`` (marca una bandera
    thread-safe); el job ``reload-watcher`` del servicio procesa la recarga
    fuera del contexto de la señal. En Windows (sin ``SIGUSR1``) o fuera del
    hilo principal no se toca ninguna señal: la recarga llega por el archivo de
    control. Al salir se restaura el handler previo.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    sig = getattr(signal, "SIGUSR1", None)
    if sig is None:
        yield
        return

    def _request_reload(signum: int, frame: Any) -> None:
        service.request_reload()

    try:
        previous = signal.getsignal(sig)
        signal.signal(sig, _request_reload)
    except (ValueError, OSError):
        yield
        return
    try:
        yield
    finally:
        signal.signal(sig, previous)


class ServiceRunner:
    """Runtime del scheduler en modo servicio (``ServiceRuntime``, Item 059).

    ``console=False`` (default) es el modo residente: logging solo a archivo y
    stdio redirigido al ``odin.log``. ``console=True`` lo usa la CLI en primer
    plano y conserva la consola. ``service_factory`` es inyectable para tests;
    el default usa ``build_scheduler_service`` (pipeline real + hook de
    recarga).
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        *,
        console: bool = False,
        service_factory: ServiceFactory | None = None,
    ) -> None:
        self._config_path = Path(config_path) if config_path is not None else None
        self._console = console
        self._service_factory = service_factory
        self._service: SchedulerService | None = None
        self._store: SchedulerStateStore | None = None
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._stopped = False

    @property
    def config_path(self) -> Path | None:
        """Ruta del JSON con la que corre el servicio (``None`` = sin fuente)."""
        return self._config_path

    @property
    def console(self) -> bool:
        """``True`` si el runner conserva la consola (primer plano)."""
        return self._console

    def run(self) -> int:
        """Carga, valida y arranca el scheduler bloqueante; devuelve exit code.

        Una fuente ausente, un JSON/estructura inválida (``ConfigError``) o
        ``scheduler.enabled: false`` se reportan en stderr y devuelven
        ``EXIT_CONFIG`` sin escribir estado. Cualquier otra excepción del
        arranque propaga (el llamador la traduce a ``EXIT_INTERNAL``) con el
        ``finally`` de ``_run_service`` garantizando el shutdown y el estado
        final.
        """
        if self._stop_requested.is_set():
            logger.info("Servicio detenido antes de arrancar: no se inicia el scheduler")
            return EXIT_OK
        source = self._resolve_config_source()
        if source is None:
            print(
                "No se indicó el archivo de configuración: use --config <ruta> "
                f"o defina la variable de entorno {ENV_CONFIG_VAR}.",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        try:
            config = load_config(source)
        except ConfigError as exc:
            print(exc, file=sys.stderr)
            return EXIT_CONFIG
        if not config.scheduler.enabled:
            print(
                "El scheduler está deshabilitado (scheduler.enabled: false): "
                "habilítelo para usar 'odin service run'.",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        log = _setup_logging_or_warn(config, console=self._console)
        if self._console:
            return self._run_service(config, log)
        log_path = config.local.resolved_log_dir / LOG_FILENAME
        with redirect_stdio_to_log(log_path):
            return self._run_service(config, log)

    def stop(self) -> None:
        """Detiene el scheduler, persiste el estado final y registra el cierre.

        Thread-safe e idempotente: la segunda invocación (y las siguientes) es
        un no-op. Un ``stop()`` previo al ``run()`` deja la parada pedida y
        ``run()`` retorna 0 sin arrancar el scheduler; si el ``stop()`` llega
        con el scheduler ya arrancado, ``SchedulerService.shutdown()`` libera
        el ``BlockingScheduler`` bloqueado. El estado final también lo persiste
        el ``finally`` de ``_run_service``.
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_requested.set()
            service, store = self._service, self._store
        if service is not None:
            service.shutdown()
        if store is not None:
            store.save()
        logger.info("Servicio detenido: scheduler parado y estado persistido")

    def _resolve_config_source(self) -> Path | None:
        """Ruta fijada en la instalación o ``ODIN_CONFIG`` (uso en foreground)."""
        if self._config_path is not None:
            return self._config_path
        raw = os.environ.get(ENV_CONFIG_VAR, "")
        if not raw.strip():
            return None
        return Path(raw)

    def _build_service(
        self, config: Config, *, state_store: SchedulerStateStore
    ) -> SchedulerService:
        return build_scheduler_service(config, state_store=state_store, console=self._console)

    def _run_service(self, config: Config, log: Logger | None) -> int:
        """Arma store + servicio, persiste el estado y arranca el scheduler."""
        store = SchedulerStateStore(
            state_path(config.local.work_dir),
            pid=os.getpid(),
            config_path=str(config.config_path),
            started_at=datetime.now(UTC),
            mask=SecretMasker.from_config(config).mask,
        )
        factory = self._service_factory or self._build_service
        service = factory(config, state_store=store)
        store.save()
        with self._lock:
            self._service = service
            self._store = store
            already_stopped = self._stop_requested.is_set()
        if log is not None:
            mode = "en primer plano" if self._console else "en modo residente"
            log.info(
                "Servicio %s: %d job(s); estado en %s",
                mode,
                len(config.scheduler.jobs),
                store.path,
            )
        if already_stopped:
            service.shutdown()
            store.save()
            return EXIT_OK
        try:
            with _stop_signals(), _reload_signal(service):
                service.start()
        except KeyboardInterrupt:
            if log is not None:
                log.info("Señal de parada recibida: deteniendo el scheduler")
        finally:
            service.shutdown()
            store.save()
        return EXIT_OK
