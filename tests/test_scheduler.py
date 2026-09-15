"""Tests del scheduler interno: helpers de calendario y servicio (Items 049-051).

Deterministas: ``next_fire_times`` recibe un ``now`` fijo y el servicio un
reloj inyectable, sin consultar el reloj del sistema (salvo el test de ciclo de
vida, que solo verifica arranque/detención). Los casos DST, de fecha imposible
y de misfire fijan la semántica real de APScheduler 3.11.3.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from odin.config import Config, SchedulerJob, load_config
from odin.scheduler import (
    CycleOutcome,
    InFlightRegistry,
    SchedulerService,
    cron_trigger,
    next_fire_times,
)

FIXTURES = Path(__file__).parent / "fixtures"
BA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
FIXED_NOW = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)  # 09:30 en Buenos Aires


@pytest.fixture(autouse=True)
def _scheduler_logs_propagate() -> None:
    """Que caplog capture el logger del scheduler aunque otro test lo haya cerrado."""
    logging.getLogger("odin.scheduler").propagate = True


def _config(
    tmp_path: Path,
    jobs: list[dict[str, Any]] | None = None,
    *,
    second_database: bool = False,
) -> Config:
    """Config Linux válida con ``work_dir`` en ``tmp_path`` y jobs a medida."""
    data: dict[str, Any] = json.loads(
        (FIXTURES / "config_valid_linux.json").read_text(encoding="utf-8")
    )
    data["local"]["work_dir"] = str(tmp_path / "work")
    if second_database:
        data["databases"].append(
            {
                **data["databases"][0],
                "name": "erp_secundaria",
                "connection": "localhost/3050:/var/lib/firebird/data/erp_secundaria.fdb",
            }
        )
    if jobs is not None:
        data["scheduler"]["jobs"] = jobs
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(str(path))


class FakeRunner:
    """``cycle_runner`` doble: registra llamadas y devuelve/levanta lo indicado."""

    def __init__(
        self, outcome: CycleOutcome | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[tuple[Config, SchedulerJob]] = []
        self._outcome = outcome
        self._error = error

    def __call__(self, config: Config, job: SchedulerJob) -> CycleOutcome:
        self.calls.append((config, job))
        if self._error is not None:
            raise self._error
        if self._outcome is not None:
            return self._outcome
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
        )


def test_cron_trigger_uses_requested_timezone() -> None:
    trigger = cron_trigger("0 2 * * *", "America/Argentina/Buenos_Aires")
    assert trigger.timezone == ZoneInfo("America/Argentina/Buenos_Aires")


def test_cron_trigger_rejects_invalid_expression() -> None:
    with pytest.raises(ValueError):
        cron_trigger("0 25 * * *", "UTC")


def test_cron_trigger_rejects_unknown_timezone() -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        cron_trigger("0 2 * * *", "Marte/Olympus_Mons")


def test_next_fire_times_daily_with_fixed_now() -> None:
    trigger = cron_trigger("0 2 * * *", "America/Argentina/Buenos_Aires")
    now = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)
    fires = next_fire_times(trigger, now, 2)
    assert [fire.isoformat() for fire in fires] == [
        "2026-09-16T02:00:00-03:00",
        "2026-09-17T02:00:00-03:00",
    ]


def test_next_fire_times_includes_fire_exactly_at_now() -> None:
    trigger = cron_trigger("0 2 * * *", "UTC")
    now = datetime(2026, 9, 16, 2, 0, tzinfo=UTC)
    assert next_fire_times(trigger, now, 1) == [now]


def test_next_fire_times_steps_are_consecutive() -> None:
    # APScheduler usa 0=lunes en day_of_week; los nombres evitan la ambigüedad.
    trigger = cron_trigger("*/15 8-18 * * mon-fri", "UTC")
    now = datetime(2026, 9, 18, 17, 50, tzinfo=UTC)  # viernes
    fires = next_fire_times(trigger, now, 3)
    assert [fire.isoformat() for fire in fires] == [
        "2026-09-18T18:00:00+00:00",
        "2026-09-18T18:15:00+00:00",
        "2026-09-18T18:30:00+00:00",
    ]


def test_next_fire_times_skips_weekend() -> None:
    trigger = cron_trigger("0 8 * * mon-fri", "UTC")
    now = datetime(2026, 9, 18, 17, 50, tzinfo=UTC)  # viernes
    fires = next_fire_times(trigger, now, 2)
    assert [fire.isoformat() for fire in fires] == [
        "2026-09-21T08:00:00+00:00",  # lunes
        "2026-09-22T08:00:00+00:00",
    ]


def test_next_fire_times_dst_spring_forward() -> None:
    # 2026-03-08 02:30 en America/New_York no existe (salto de primavera):
    # APScheduler 3.x conserva el offset previo (-05:00), que corresponde al
    # instante 07:30 UTC (03:30 local EDT). Se compara el instante en UTC
    # porque comparar datetimes con distinto tzinfo en un hueco DST es
    # engañoso.
    trigger = cron_trigger("30 2 * * *", "America/New_York")
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    fires = next_fire_times(trigger, now, 1)
    assert fires[0].astimezone(UTC) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert fires[0].isoformat() == "2026-03-08T02:30:00-05:00"


def test_next_fire_times_impossible_date_returns_empty() -> None:
    trigger = cron_trigger("0 0 31 2 *", "UTC")
    assert next_fire_times(trigger, datetime(2026, 1, 1, tzinfo=UTC), 3) == []


# --- SchedulerService: registro y ciclo de vida (Item 050) ---


def test_service_registers_one_job_per_entry(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {"databases": ["erp_principal"], "schedule": "30 3 * * 6", "on_misfire": "skip"},
    ]
    service = SchedulerService(
        _config(tmp_path, jobs), cycle_runner=FakeRunner(), now=lambda: FIXED_NOW
    )
    registered = {job.id: job for job in service.scheduler.get_jobs()}
    assert set(registered) == {"job-0", "job-1"}
    assert registered["job-0"].args == ("job-0",)
    assert registered["job-0"].max_instances == 1
    assert registered["job-0"].trigger.timezone == BA_TZ
    assert str(registered["job-0"].trigger) == str(cron_trigger("0 2 * * *", str(BA_TZ)))
    assert str(registered["job-1"].trigger) == str(
        cron_trigger("30 3 * * 6", str(BA_TZ))
    )
    expected = next_fire_times(cron_trigger("0 2 * * *", str(BA_TZ)), FIXED_NOW, 1)[0]
    assert registered["job-0"].next_run_time == expected
    assert service.timezone == BA_TZ
    assert service.scheduler.timezone == BA_TZ


def test_run_job_invokes_cycle_runner_and_records_outcome(tmp_path: Path) -> None:
    config = _config(tmp_path)
    expected = CycleOutcome(
        job_databases=("erp_principal",),
        databases=("erp_principal",),
        success=True,
        duration_seconds=0.4,
        notification_sent=True,
    )
    runner = FakeRunner(outcome=expected)
    service = SchedulerService(config, cycle_runner=runner, now=lambda: FIXED_NOW)
    result = service.run_job("job-0")
    assert runner.calls == [(config, config.scheduler.jobs[0])]
    assert result == expected
    assert service.last_outcomes["job-0"] == expected


def test_run_job_isolates_cycle_runner_exception(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = SchedulerService(
        _config(tmp_path),
        cycle_runner=FakeRunner(error=RuntimeError("boom")),
        now=lambda: FIXED_NOW,
    )
    with caplog.at_level(logging.ERROR, logger="odin.scheduler"):
        outcome = service.run_job("job-0")
    assert outcome.success is False
    assert outcome.skipped is False
    assert outcome.error_message is not None
    assert "boom" in outcome.error_message
    assert "job-0" in caplog.text
    assert service.last_outcomes["job-0"] is outcome


def test_start_blocks_until_shutdown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = SchedulerService(_config(tmp_path), cycle_runner=FakeRunner())
    with caplog.at_level(logging.INFO, logger="odin.scheduler"):
        thread = threading.Thread(target=service.start, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not service.scheduler.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.scheduler.running
        service.shutdown()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not service.scheduler.running
    service.shutdown()  # idempotente: no lanza si ya está detenido
    assert "Scheduler iniciado" in caplog.text
    assert "Scheduler detenido" in caplog.text


# --- anti-solapamiento y misfire (Item 051) ---


def test_in_flight_registry_all_or_nothing() -> None:
    registry = InFlightRegistry()
    first = registry.reserve(["a", "b"], all_or_nothing=True)
    assert first.reserved == ("a", "b")
    assert first.busy == ()
    conflict = registry.reserve(["b", "c"], all_or_nothing=True)
    assert conflict.reserved == ()
    assert conflict.busy == ("b",)
    free = registry.reserve(["b", "c"], all_or_nothing=False)
    assert free.reserved == ("c",)
    assert free.busy == ("b",)
    assert registry.busy() == frozenset({"a", "b", "c"})
    registry.release(["a", "b", "c"])
    assert registry.busy() == frozenset()
    registry.release(["a"])  # liberar una libre es idempotente


def test_overlapping_job_is_skipped(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
    ]
    entered = threading.Event()
    release = threading.Event()

    def runner(config: Config, job: SchedulerJob) -> CycleOutcome:
        entered.set()
        assert release.wait(timeout=5)
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
        )

    service = SchedulerService(
        _config(tmp_path, jobs), cycle_runner=runner, now=lambda: FIXED_NOW
    )
    worker = threading.Thread(target=service.run_job, args=("job-0",), daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        overlap = service.run_job("job-1")
        assert overlap.skipped is True
        assert overlap.skipped_reason is not None
        assert "erp_principal" in overlap.skipped_reason
        assert service.last_outcomes["job-1"] is overlap
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    later = service.run_job("job-1")
    assert later.skipped is False
    assert later.success is True


def test_skip_if_running_false_runs_only_free_databases(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {
            "databases": ["erp_principal", "erp_secundaria"],
            "schedule": "0 2 * * *",
            "skip_if_running": False,
        },
    ]
    entered = threading.Event()
    release = threading.Event()

    def runner(config: Config, job: SchedulerJob) -> CycleOutcome:
        if list(job.databases) == ["erp_principal"]:
            entered.set()
            assert release.wait(timeout=5)
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
        )

    service = SchedulerService(
        _config(tmp_path, jobs, second_database=True),
        cycle_runner=runner,
        now=lambda: FIXED_NOW,
    )
    worker = threading.Thread(target=service.run_job, args=("job-0",), daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        partial = service.run_job("job-1")
        assert partial.skipped is False
        assert partial.job_databases == ("erp_principal", "erp_secundaria")
        assert partial.databases == ("erp_secundaria",)
    finally:
        release.set()
        worker.join(timeout=5)


def test_skip_if_running_true_skips_whole_job_if_any_base_busy(
    tmp_path: Path,
) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {"databases": ["erp_principal", "erp_secundaria"], "schedule": "0 2 * * *"},
    ]
    entered = threading.Event()
    release = threading.Event()

    def runner(config: Config, job: SchedulerJob) -> CycleOutcome:
        entered.set()
        assert release.wait(timeout=5)
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
        )

    service = SchedulerService(
        _config(tmp_path, jobs, second_database=True),
        cycle_runner=runner,
        now=lambda: FIXED_NOW,
    )
    worker = threading.Thread(target=service.run_job, args=("job-0",), daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        skipped = service.run_job("job-1")
        assert skipped.skipped is True
        assert skipped.skipped_reason is not None
        assert "erp_principal" in skipped.skipped_reason
    finally:
        release.set()
        worker.join(timeout=5)


def test_skip_if_running_false_with_all_bases_busy_is_skipped(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal", "erp_secundaria"], "schedule": "0 2 * * *"},
        {
            "databases": ["erp_principal", "erp_secundaria"],
            "schedule": "0 2 * * *",
            "skip_if_running": False,
        },
    ]
    entered = threading.Event()
    release = threading.Event()

    def runner(config: Config, job: SchedulerJob) -> CycleOutcome:
        entered.set()
        assert release.wait(timeout=5)
        return CycleOutcome(
            job_databases=tuple(job.databases),
            databases=tuple(job.databases),
            success=True,
        )

    service = SchedulerService(
        _config(tmp_path, jobs, second_database=True),
        cycle_runner=runner,
        now=lambda: FIXED_NOW,
    )
    worker = threading.Thread(target=service.run_job, args=("job-0",), daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        skipped = service.run_job("job-1")
        assert skipped.skipped is True
        assert skipped.skipped_reason is not None
        assert "erp_principal" in skipped.skipped_reason
    finally:
        release.set()
        worker.join(timeout=5)


def test_bases_are_released_after_runner_failure(tmp_path: Path) -> None:
    registry = InFlightRegistry()
    service = SchedulerService(
        _config(tmp_path),
        cycle_runner=FakeRunner(error=RuntimeError("boom")),
        now=lambda: FIXED_NOW,
        in_flight=registry,
    )
    outcome = service.run_job("job-0")
    assert outcome.success is False
    assert registry.busy() == frozenset()
    assert service.run_job("job-0").skipped is False


def test_misfire_skip_discards_late_fire(tmp_path: Path) -> None:
    now = [FIXED_NOW]
    jobs = [{"databases": ["erp_principal"], "schedule": "* * * * *", "on_misfire": "skip"}]
    runner = FakeRunner()
    service = SchedulerService(
        _config(tmp_path, jobs), cycle_runner=runner, now=lambda: now[0]
    )
    now[0] = datetime(2026, 9, 15, 12, 36, tzinfo=UTC)  # 5 min tarde
    outcome = service.run_job("job-0")
    assert outcome.skipped is True
    assert outcome.skipped_reason is not None
    assert "vencido" in outcome.skipped_reason
    assert runner.calls == []


def test_misfire_run_once_executes_late_fire(tmp_path: Path) -> None:
    now = [FIXED_NOW]
    jobs = [
        {"databases": ["erp_principal"], "schedule": "* * * * *", "on_misfire": "run_once"}
    ]
    runner = FakeRunner()
    service = SchedulerService(
        _config(tmp_path, jobs), cycle_runner=runner, now=lambda: now[0]
    )
    now[0] = datetime(2026, 9, 15, 12, 36, tzinfo=UTC)
    outcome = service.run_job("job-0")
    assert outcome.skipped is False
    assert outcome.success is True
    assert len(runner.calls) == 1


def test_misfire_policies_configure_apscheduler_job(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {
            "databases": ["erp_principal"],
            "schedule": "0 2 * * *",
            "on_misfire": "skip",
        },
    ]
    service = SchedulerService(
        _config(tmp_path, jobs), cycle_runner=FakeRunner(), now=lambda: FIXED_NOW
    )
    run_once = service.scheduler.get_job("job-0")
    skip = service.scheduler.get_job("job-1")
    assert run_once is not None and skip is not None
    assert run_once.coalesce is True
    assert run_once.misfire_grace_time is None
    assert skip.coalesce is True
    assert skip.misfire_grace_time == 1

