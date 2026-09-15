"""Tests del `service status` compuesto: gestor del SO + scheduler (Item 063).

Sin systemd ni pywin32: el estado del gestor se construye con ``ServiceStatus``
prefabricados y el del scheduler con ``SchedulerStateStore`` sobre ``tmp_path``
o con ``StateLoadResult`` sintéticos (estado ausente/obsoleto). El cableado CLI
se cubre en ``tests/test_cli.py``; la verificación de integración de la unit
queda para el Item 066.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from odin.config import SchedulerJob
from odin.scheduler import (
    CycleOutcome,
    SchedulerStateStore,
    StateLoadResult,
    render_service_status,
)
from odin.service import (
    ServiceManagerKind,
    ServiceStatus,
    render_platform_status,
)


def _store(tmp_path: Path) -> SchedulerStateStore:
    """Store con un job y un ciclo exitoso (mismo patrón que test_cli)."""
    store = SchedulerStateStore(
        tmp_path / "scheduler_state.json",
        pid=4242,
        config_path=str(tmp_path / "config.json"),
        started_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
        clock=lambda: datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    )
    store.register_job(
        "job-0",
        SchedulerJob(databases=["erp_principal"], schedule="0 2 * * *"),
        next_fire_time=datetime(2026, 9, 16, 2, 0, tzinfo=UTC),
    )
    store.record_cycle(
        "job-0",
        CycleOutcome(
            job_databases=("erp_principal",),
            databases=("erp_principal",),
            success=True,
            duration_seconds=1.2,
            notification_sent=True,
        ),
        next_fire_time=datetime(2026, 9, 17, 2, 0, tzinfo=UTC),
    )
    return store


def _running_state(tmp_path: Path) -> StateLoadResult:
    store = _store(tmp_path)
    return StateLoadResult(store.snapshot(), store.path, stale=False)


def _stale_state(tmp_path: Path) -> StateLoadResult:
    store = _store(tmp_path)
    return StateLoadResult(store.snapshot(), store.path, stale=True)


def _missing_state(tmp_path: Path) -> StateLoadResult:
    return StateLoadResult(
        None,
        tmp_path / "scheduler_state.json",
        warning="no existe el archivo de estado (todavía no corrió el servicio)",
    )


def test_not_installed_platform_suggests_install(tmp_path: Path) -> None:
    text = render_platform_status(
        ServiceStatus.not_installed(ServiceManagerKind.SYSTEMD, detail="LoadState=not-found"),
        render_service_status(_missing_state(tmp_path)),
    )
    assert "Servicio del SO (systemd): no instalado" in text
    assert "odin service install --config <ruta>" in text
    assert "Scheduler:" in text
    assert "Servicio ODIN: sin estado" in text


def test_installed_and_stopped_platform_suggests_start(tmp_path: Path) -> None:
    status = ServiceStatus(
        installed=True,
        running=False,
        auto_start=True,
        restart_on_failure=False,
        manager=ServiceManagerKind.SYSTEMD,
        detail="LoadState=loaded, ActiveState=inactive",
    )
    text = render_platform_status(status, render_service_status(_running_state(tmp_path)))
    assert "Servicio del SO (systemd): instalado y detenido" in text
    assert "Arranque automático: sí" in text
    assert "Reinicio ante caída: no" in text
    assert "Detalle: LoadState=loaded, ActiveState=inactive" in text
    assert "odin service start" in text
    assert "Servicio ODIN: en ejecución (pid 4242)" in text


def test_installed_and_running_platform_has_no_start_suggestion(tmp_path: Path) -> None:
    status = ServiceStatus(
        installed=True,
        running=True,
        auto_start=True,
        restart_on_failure=True,
        manager=ServiceManagerKind.WINDOWS,
        detail="SERVICE_RUNNING",
    )
    text = render_platform_status(status, render_service_status(_running_state(tmp_path)))
    assert "Servicio del SO (windows): en ejecución" in text
    assert "Detalle: SERVICE_RUNNING" in text
    assert "odin service start" not in text
    assert "Último ciclo: success en 1.2 s (erp_principal; correo enviado)" in text


def test_running_platform_with_stale_scheduler_state_is_visible(tmp_path: Path) -> None:
    status = ServiceStatus(
        installed=True,
        running=True,
        manager=ServiceManagerKind.SYSTEMD,
        detail="ActiveState=active",
    )
    text = render_platform_status(status, render_service_status(_stale_state(tmp_path)))
    assert "Servicio del SO (systemd): en ejecución" in text
    assert "Servicio ODIN: detenido (pid 4242 ya no está en ejecución)" in text


def test_manager_warning_still_renders_scheduler_section(tmp_path: Path) -> None:
    text = render_platform_status(
        None,
        render_service_status(_running_state(tmp_path)),
        warning="systemctl no disponible",
    )
    assert "Servicio del SO: no se pudo consultar el gestor (systemctl no disponible)" in text
    assert "Servicio ODIN: en ejecución (pid 4242)" in text


def test_unknown_platform_status_without_warning(tmp_path: Path) -> None:
    text = render_platform_status(None, render_service_status(_missing_state(tmp_path)))
    assert "Servicio del SO: estado desconocido" in text
    assert "Servicio ODIN: sin estado" in text


def test_missing_manager_flags_render_as_unknown(tmp_path: Path) -> None:
    status = ServiceStatus(
        installed=True, running=True, manager=ServiceManagerKind.SYSTEMD, detail=None
    )
    text = render_platform_status(status, render_service_status(_missing_state(tmp_path)))
    assert "Arranque automático: desconocido" in text
    assert "Reinicio ante caída: desconocido" in text
    assert "Detalle:" not in text
