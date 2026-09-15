"""Tests del runner compartido del modo servicio (Item 065).

Sin systemd/SCM/pywin32: el runner se ejerce con `SchedulerService` reales
(cycle_runner doble, trigger acelerado, hilos) y con servicios dobles, la
configuración sale del fixture Linux mutado a `tmp_path` y el único efecto
externo es un archivo de log temporal.

Cubre:

- arranque en un hilo y parada con `stop()` desde el hilo principal dentro de
  un timeout (sin cuelgue), con estado final persistido y `stop()` idempotente;
- `stop()` previo al `run()` (la carrera arranque/parada del gestor) y el
  ajuste de `SchedulerService.shutdown()` que la cierra;
- fuente ausente / JSON inválido / scheduler deshabilitado → exit 2 sin
  arrancar;
- logging del modo residente (sin consola, stdio redirigido al `odin.log`) y
  primer plano (consola conservada);
- el hook de recarga de la fábrica por defecto re-configura el logging;
- el contrato de exit codes del runner es el del CLI.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from odin import cli as cli_module
from odin.config import Config, load_config
from odin.log import LOG_FILENAME, LOGGER_NAME, setup_logging
from odin.scheduler import (
    CycleOutcome,
    SchedulerService,
    SchedulerStateStore,
    load_state,
    state_path,
)
from odin.service.runner import (
    EXIT_CONFIG,
    EXIT_INTERNAL,
    EXIT_OK,
    ServiceRunner,
    _reload_signal,
    _stop_signals,
    build_scheduler_service,
)

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
FAR_FUTURE_SCHEDULE = "0 3 1 1 *"
FAST_CADENCE_SECONDS = 1
POLL_SECONDS = 0.02
HAS_SIGUSR1 = hasattr(signal, "SIGUSR1")


@pytest.fixture(autouse=True)
def clean_odin_logger() -> Iterator[None]:
    """Limpia el logger ``odin`` tras cada test (sin handlers abiertos)."""
    yield
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de un ``ODIN_CONFIG`` presente en el entorno real."""
    monkeypatch.delenv("ODIN_CONFIG", raising=False)


def _write_config(
    tmp_path: Path, *, schedule: str = FAR_FUTURE_SCHEDULE, enabled: bool = True
) -> Path:
    """Copia el fixture Linux con ``work_dir``, SMTP y horario controlados."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = 0
    data["servers"] = []
    data["scheduler"]["enabled"] = enabled
    data["scheduler"]["timezone"] = "UTC"
    data["scheduler"]["jobs"][0]["schedule"] = schedule
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _wait_until(condition: Callable[[], bool], *, timeout: float, what: str) -> None:
    """Espera activa con deadline: falla con contexto si ``condition`` no llega."""
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"timeout de {timeout:.0f}s esperando {what}")
        time.sleep(POLL_SECONDS)


class _NoopCycleRunner:
    """``cycle_runner`` doble: ciclo exitoso sin pipeline ni red."""

    def __call__(self, config: Config, job: Any) -> CycleOutcome:
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
            duration_seconds=0.0,
            notification_sent=True,
        )


class _CountingService:
    """Envuelve un ``SchedulerService`` real y cuenta sus ``shutdown()``."""

    def __init__(self, inner: SchedulerService) -> None:
        self.inner = inner
        self.shutdown_calls = 0

    @property
    def scheduler(self) -> Any:
        return self.inner.scheduler

    def start(self) -> None:
        self.inner.start()

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdown_calls += 1
        self.inner.shutdown(wait=wait)

    def request_reload(self) -> None:
        self.inner.request_reload()


class _PrintingService:
    """Servicio doble: imprime a stdout/stderr y termina de inmediato."""

    def __init__(self) -> None:
        self.shutdown_calls = 0

    def start(self) -> None:
        print("salida de consola del servicio")
        print("error de consola del servicio", file=sys.stderr)

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdown_calls += 1


def _factory_capturing(
    captured: list[SchedulerService],
) -> Callable[..., SchedulerService]:
    def factory(config: Config, *, state_store: SchedulerStateStore) -> SchedulerService:
        service = SchedulerService(
            config, cycle_runner=_NoopCycleRunner(), state_store=state_store
        )
        captured.append(service)
        return service

    return factory


def _factory_that_must_not_run() -> Callable[..., SchedulerService]:
    def factory(config: Config, *, state_store: SchedulerStateStore) -> SchedulerService:
        raise AssertionError("la fábrica del servicio no debía ejecutarse")

    return factory


# --- test_run_and_stop ---


def test_run_stops_from_another_thread_and_persists_final_state(tmp_path: Path) -> None:
    """El gestor detiene un scheduler real bloqueado sin colgar el proceso."""
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    captured: list[_CountingService] = []

    def factory(config: Config, *, state_store: SchedulerStateStore) -> SchedulerService:
        wrapper = _CountingService(
            SchedulerService(config, cycle_runner=_NoopCycleRunner(), state_store=state_store)
        )
        captured.append(wrapper)
        return wrapper  # type: ignore[return-value]

    runner = ServiceRunner(config_path, console=True, service_factory=factory)
    result: dict[str, int] = {}

    def target() -> None:
        result["code"] = runner.run()

    thread = threading.Thread(target=target, name="odin-service-runner", daemon=True)
    thread.start()
    try:
        _wait_until(
            lambda: bool(captured) and captured[0].scheduler.running,
            timeout=10,
            what="scheduler en ejecución",
        )
        service = captured[0]
        timezone = service.scheduler.timezone
        service.scheduler.modify_job(
            "job-0",
            trigger=IntervalTrigger(seconds=FAST_CADENCE_SECONDS, timezone=timezone),
            next_run_time=datetime.now(timezone),
        )
        _wait_until(
            lambda: service.inner.last_outcomes.get("job-0") is not None,
            timeout=10,
            what="primer ciclo del job",
        )
        runner.stop()
    finally:
        if captured and captured[0].scheduler.running:
            captured[0].shutdown()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result.get("code") == EXIT_OK

    first_shutdowns = captured[0].shutdown_calls
    runner.stop()  # stop() repetido es no-op
    assert captured[0].shutdown_calls == first_shutdowns

    state = load_state(state_path(config.local.work_dir))
    assert state.state is not None
    assert state.stale is False
    assert state.state.pid == os.getpid()
    assert [job.job_id for job in state.state.jobs] == ["job-0"]
    assert state.state.jobs[0].last_cycle is not None
    assert state.state.jobs[0].last_cycle.notification_sent is True


def test_stop_before_run_returns_ok_without_starting(tmp_path: Path) -> None:
    """Un stop() previo al run() deja la parada pedida y no arranca nada."""
    config_path = _write_config(tmp_path)

    runner = ServiceRunner(
        config_path, console=True, service_factory=_factory_that_must_not_run()
    )
    runner.stop()
    assert runner.run() == EXIT_OK
    assert not state_path(load_config(config_path).local.work_dir).exists()


def test_run_internal_error_shuts_down_and_persists_state(tmp_path: Path) -> None:
    """Un fallo imprevisto de start() no saltea el shutdown ni el estado."""
    config_path = _write_config(tmp_path)
    config = load_config(config_path)

    class _FailingService:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def start(self) -> None:
            raise RuntimeError("fallo inesperado del executor")

        def shutdown(self, *, wait: bool = True) -> None:
            self.shutdown_calls += 1

    service = _FailingService()

    def factory(config: Config, *, state_store: SchedulerStateStore) -> Any:
        return service

    runner = ServiceRunner(config_path, console=True, service_factory=factory)
    with pytest.raises(RuntimeError, match="fallo inesperado"):
        runner.run()
    assert service.shutdown_calls == 1
    assert state_path(config.local.work_dir).exists()


# --- configuración ---


def test_run_without_config_source_exits_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ODIN_CONFIG", raising=False)
    runner = ServiceRunner(console=True, service_factory=_factory_that_must_not_run())
    assert runner.run() == EXIT_CONFIG
    assert "No se indicó el archivo de configuración" in capsys.readouterr().err


def test_run_resolves_odin_config_env_in_foreground(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ruta fijada, el foreground resuelve ``ODIN_CONFIG`` (Item 065)."""
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("ODIN_CONFIG", str(config_path))
    service = _PrintingService()
    runner = ServiceRunner(
        console=True, service_factory=lambda config, *, state_store: service
    )
    assert runner.run() == EXIT_OK
    assert service.shutdown_calls == 1


def test_run_with_invalid_config_exits_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{esto no es json", encoding="utf-8")
    runner = ServiceRunner(
        config_path, console=True, service_factory=_factory_that_must_not_run()
    )
    assert runner.run() == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err


def test_run_with_disabled_scheduler_exits_config_without_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, enabled=False)
    runner = ServiceRunner(
        config_path, console=True, service_factory=_factory_that_must_not_run()
    )
    assert runner.run() == EXIT_CONFIG
    assert "deshabilitado" in capsys.readouterr().err
    assert not state_path(load_config(config_path).local.work_dir).exists()


# --- logging ---


def test_resident_mode_logs_without_console_and_redirects_stdio(tmp_path: Path) -> None:
    """Sin consola: un solo handler de archivo y stdio redirigido al log."""
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    service = _PrintingService()
    runner = ServiceRunner(
        config_path,
        service_factory=lambda config, *, state_store: service,
    )
    original_out, original_err = sys.stdout, sys.stderr

    assert runner.run() == EXIT_OK

    assert sys.stdout is original_out
    assert sys.stderr is original_err
    logger = logging.getLogger(LOGGER_NAME)
    assert [type(handler).__name__ for handler in logger.handlers] == [
        "RotatingFileHandler"
    ]
    log_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "salida de consola del servicio" in log_text
    assert "error de consola del servicio" in log_text
    assert "Servicio en modo residente" in log_text


def test_foreground_mode_keeps_console(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Con consola: el print se ve en pantalla y el log conserva la modalidad."""
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    service = _PrintingService()
    runner = ServiceRunner(
        config_path,
        console=True,
        service_factory=lambda config, *, state_store: service,
    )

    assert runner.run() == EXIT_OK

    assert "salida de consola del servicio" in capsys.readouterr().out
    logger = logging.getLogger(LOGGER_NAME)
    assert len(logger.handlers) == 2
    log_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Servicio en primer plano" in log_text


def test_default_factory_reload_hook_reconfigures_logging(tmp_path: Path) -> None:
    """La fábrica real re-aplica setup_logging en la recarga en caliente."""
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    store = SchedulerStateStore(
        state_path(config.local.work_dir),
        pid=os.getpid(),
        config_path=str(config.config_path),
        started_at=datetime.now(UTC),
    )
    setup_logging(config, console=False)  # modalidad residente, como el runner
    service = build_scheduler_service(config, state_store=store, console=False)
    logger = logging.getLogger(LOGGER_NAME)
    assert [type(handler).__name__ for handler in logger.handlers] == [
        "RotatingFileHandler"
    ]

    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    data["local"]["log_level"] = "DEBUG"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    service.request_reload()

    assert service.process_reload() is True
    assert logger.level == logging.DEBUG
    assert [type(handler).__name__ for handler in logger.handlers] == [
        "RotatingFileHandler"
    ]


# --- contrato e helpers de señal ---


def test_runner_exit_codes_match_cli_contract() -> None:
    """Los exit codes del runner replican el contrato público del CLI."""
    assert (EXIT_OK, EXIT_INTERNAL, EXIT_CONFIG) == (
        cli_module.EXIT_OK,
        cli_module.EXIT_INTERNAL,
        cli_module.EXIT_CONFIG,
    )


class _FakeReloadService:
    """Doble mínimo para el handler de SIGUSR1: cuenta solicitudes."""

    def __init__(self) -> None:
        self.reload_requests = 0

    def request_reload(self) -> None:
        self.reload_requests += 1


def test_stop_signals_installs_and_restores_handlers() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    with _stop_signals():
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) is previous


def test_reload_signal_requests_reload_and_restores_handler() -> None:
    if not HAS_SIGUSR1:
        pytest.skip("la plataforma no tiene SIGUSR1")
    service = _FakeReloadService()
    previous = signal.getsignal(signal.SIGUSR1)
    with _reload_signal(service):  # type: ignore[arg-type]
        handler = signal.getsignal(signal.SIGUSR1)
        assert handler is not previous
        handler(signal.SIGUSR1, None)
    assert service.reload_requests == 1
    assert signal.getsignal(signal.SIGUSR1) is previous
