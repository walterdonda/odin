"""Tests del estado consultable del servicio (Item 052).

Sin servicios externos: solo filesystem temporal, JSON y stdlib. La escritura
atómica se prueba con un fallo simulado de ``os.replace`` y la detección de
estado obsoleto con pids controlados (el propio proceso y uno imposible).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from odin.config import Config, load_config
from odin.log import SecretMasker
from odin.scheduler import (
    MAX_RECENT_ERRORS,
    SCHEMA_VERSION,
    STATE_FILENAME,
    CycleOutcome,
    CycleStatus,
    SchedulerStateStore,
    load_state,
    pid_is_alive,
    state_path,
    write_state,
)

FIXTURES = Path(__file__).parent / "fixtures"
STARTED_AT = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
CLOCK_NOW = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)
DEAD_PID = 2**31 - 1  # fuera de cualquier rango de pids real


def _config(
    tmp_path: Path, jobs: list[dict[str, Any]] | None = None, *, second_database: bool = False
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


def _store(
    config: Config, *, pid: int | None = None, mask: Any = None, **kwargs: Any
) -> SchedulerStateStore:
    """Store con reloj fijo y pid del proceso actual salvo indicación."""
    return SchedulerStateStore(
        state_path(config.local.work_dir),
        pid=os.getpid() if pid is None else pid,
        config_path=str(config.config_path),
        started_at=STARTED_AT,
        mask=mask,
        clock=lambda: CLOCK_NOW,
        **kwargs,
    )


def _success(name: str) -> CycleOutcome:
    return CycleOutcome(
        job_databases=(name,),
        databases=(name,),
        success=True,
        duration_seconds=1.5,
        notification_sent=True,
    )


def _failure(name: str, message: str) -> CycleOutcome:
    return CycleOutcome(
        job_databases=(name,),
        databases=(name,),
        success=False,
        duration_seconds=0.5,
        error_message=message,
    )


# --- round trip y atomicidad ---


def test_state_round_trip(tmp_path: Path) -> None:
    jobs = [
        {"databases": ["erp_principal"], "schedule": "0 2 * * *"},
        {"databases": ["erp_principal", "erp_secundaria"], "schedule": "30 3 * * *"},
    ]
    config = _config(tmp_path, jobs, second_database=True)
    store = _store(config)
    for index, job in enumerate(config.scheduler.jobs):
        store.register_job(f"job-{index}", job, next_fire_time=CLOCK_NOW)
    store.record_cycle("job-0", _success("erp_principal"), next_fire_time=CLOCK_NOW)
    store.record_cycle(
        "job-1", _failure("erp_secundaria", "gbak falló"), next_fire_time=CLOCK_NOW
    )
    saved = store.save()

    assert saved == state_path(config.local.work_dir)
    assert saved.name == STATE_FILENAME
    result = load_state(saved)
    assert result.state is not None
    assert result.warning is None
    assert result.stale is False
    assert result.state == store.snapshot()
    assert [job.job_id for job in result.state.jobs] == ["job-0", "job-1"]
    assert result.state.jobs[0].last_cycle is not None
    assert result.state.jobs[0].last_cycle.status is CycleStatus.SUCCESS
    assert result.state.jobs[1].last_cycle is not None
    assert result.state.jobs[1].last_cycle.status is CycleStatus.FAILURE
    assert result.state.jobs[1].next_fire_time == CLOCK_NOW
    assert result.state.recent_errors == ("job-1: failure: gbak falló",)
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["version"] == SCHEMA_VERSION
    assert payload["pid"] == os.getpid()


def test_write_state_failure_keeps_previous_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store = _store(config)
    store.register_job("job-0", config.scheduler.jobs[0])
    path = store.save()
    previous = path.read_text(encoding="utf-8")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", boom)
    store.record_error("otro error")
    with pytest.raises(OSError):
        store.save()

    assert path.read_text(encoding="utf-8") == previous
    leftovers = [entry.name for entry in path.parent.iterdir() if entry.name.endswith(".tmp")]
    assert leftovers == []


def test_snapshot_does_not_touch_disk(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = _store(config)
    store.register_job("job-0", config.scheduler.jobs[0])
    state = store.snapshot()
    assert state.version == SCHEMA_VERSION
    assert state.jobs[0].last_cycle is None
    assert not store.path.exists()


# --- lectura tolerante ---


def test_load_state_missing_file_returns_warning(tmp_path: Path) -> None:
    result = load_state(tmp_path / STATE_FILENAME)
    assert result.state is None
    assert result.stale is False
    assert result.warning is not None
    assert "no existe" in result.warning


def test_load_state_corrupt_json_returns_warning(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text("{esto no es json", encoding="utf-8")
    result = load_state(path)
    assert result.state is None
    assert result.warning is not None
    assert "ilegible" in result.warning


def test_load_state_unknown_schema_returns_warning(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text(json.dumps({"version": 99, "pid": os.getpid()}), encoding="utf-8")
    result = load_state(path)
    assert result.state is None
    assert result.warning is not None
    assert "esquema desconocido" in result.warning


def test_load_state_missing_fields_returns_warning(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text(json.dumps({"version": SCHEMA_VERSION}), encoding="utf-8")
    result = load_state(path)
    assert result.state is None
    assert result.warning is not None


def test_load_state_dead_pid_is_stale(tmp_path: Path) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("la vigencia del pid no se verifica en Windows")
    config = _config(tmp_path)
    store = _store(config, pid=DEAD_PID)
    store.register_job("job-0", config.scheduler.jobs[0])
    result = load_state(store.save())
    assert result.state is not None
    assert result.stale is True


def test_pid_is_alive_reports_current_and_impossible_pids() -> None:
    assert pid_is_alive(os.getpid()) is True
    assert pid_is_alive(0) is False
    assert pid_is_alive(-1) is False
    if not sys.platform.startswith("win"):
        assert pid_is_alive(DEAD_PID) is False


# --- máscara de secretos, ventana de errores y status ---


def test_state_never_contains_secrets(tmp_path: Path) -> None:
    config = _config(tmp_path)
    secret = config.databases[0].password
    assert secret
    store = _store(config, mask=SecretMasker.from_config(config).mask)
    store.register_job("job-0", config.scheduler.jobs[0])
    store.record_cycle("job-0", _failure("erp_principal", f"gbak falló con {secret}"))
    saved = store.save()

    content = saved.read_text(encoding="utf-8")
    assert secret not in content
    assert "***" in content
    result = load_state(saved)
    assert result.state is not None
    assert result.state.recent_errors == ("job-0: failure: gbak falló con ***",)
    assert result.state.jobs[0].last_cycle is not None
    assert result.state.jobs[0].last_cycle.error_message == "gbak falló con ***"


def test_recent_errors_are_bounded(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = _store(config, max_recent_errors=2)
    store.register_job("job-0", config.scheduler.jobs[0])
    for index in range(3):
        store.record_cycle("job-0", _failure("erp_principal", f"error {index}"))
    assert store.snapshot().recent_errors == ("job-0: failure: error 1", "job-0: failure: error 2")
    assert MAX_RECENT_ERRORS >= 2


def test_register_job_preserves_last_cycle_and_next_fire(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = _store(config)
    job = config.scheduler.jobs[0]
    store.register_job("job-0", job, next_fire_time=CLOCK_NOW)
    store.record_cycle("job-0", _success("erp_principal"))
    store.register_job("job-0", job, next_fire_time=None)
    state = store.snapshot()
    assert state.jobs[0].last_cycle is not None
    assert state.jobs[0].next_fire_time is None


def test_cycle_outcome_status_derivation() -> None:
    success = CycleOutcome(job_databases=("a",), databases=("a",), success=True)
    assert success.status is CycleStatus.SUCCESS
    partial = CycleOutcome(job_databases=("a",), databases=("a",), partial=True)
    assert partial.status is CycleStatus.PARTIAL
    failure = CycleOutcome(job_databases=("a",), databases=("a",))
    assert failure.status is CycleStatus.FAILURE
    skipped = CycleOutcome(job_databases=("a",), skipped=True, skipped_reason="ocupada")
    assert skipped.status is CycleStatus.SKIPPED
    skipped_success = CycleOutcome(job_databases=("a",), skipped=True, success=True)
    assert skipped_success.status is CycleStatus.SKIPPED
    replaced = CycleOutcome(job_databases=("a",), databases=("a",), partial=True)
    assert replaced.status is CycleStatus.PARTIAL
    assert replaced == CycleOutcome(job_databases=("a",), databases=("a",), partial=True)


def test_record_cycle_for_unknown_job_creates_entry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = _store(config)
    store.record_cycle("job-9", _success("erp_principal"))
    state = store.snapshot()
    assert state.jobs[0].job_id == "job-9"
    assert state.jobs[0].databases == ("erp_principal",)
    assert state.jobs[0].last_cycle is not None


def test_write_state_creates_parent_directory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = _store(config)
    store.register_job("job-0", config.scheduler.jobs[0])
    target = tmp_path / "nuevo" / STATE_FILENAME
    write_state(target, store.snapshot())
    assert target.exists()
    assert load_state(target).state is not None
