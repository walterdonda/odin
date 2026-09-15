"""Tests de la CLI de ODIN: subcomando validate, exit codes y cableado (Items 005 y 006).

In-process: se invoca ``main([...])`` con ``capsys``/``monkeypatch`` (sin
subprocess). El helper de configs reimplementa localmente el patrón de
``tests/test_log.py`` (copiar el fixture válido Linux y mutar lo necesario)
para no acoplar módulos de test.

Los casos del Item 006 agregan validación de entorno: fijan permisos del JSON y
una clave privada local para no depender de archivos del desarrollador.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import shutil
import signal
import sys
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import py7zr
import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.cli import (
    ENV_CONFIG_VAR,
    EXIT_CONFIG,
    EXIT_FAILURE,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_PARTIAL,
    _reload_signal,
    _service_executable,
    _stop_signals,
    main,
)
from odin.config import Config, load_config
from odin.log import LOG_FILENAME, LOGGER_NAME
from odin.notify import NotificationResult, ReportMessage
from odin.retention import RetentionError, RetentionResult
from odin.scheduler import (
    RELOAD_REQUEST_FILENAME,
    CycleOutcome,
    SchedulerStateStore,
    load_state,
    state_path,
)
from odin.service import (
    ServiceError,
    ServiceManagerKind,
    ServiceSpec,
    ServiceStatus,
    ServiceUnsupportedError,
)
from odin.transfer import TransferResult

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
WINDOWS_FIXTURE = FIXTURES / "config_valid_windows.json"


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
    monkeypatch.delenv(ENV_CONFIG_VAR, raising=False)


def _write_config(
    tmp_path: Path,
    *,
    work_dir: Path | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    name: str = "config.json",
    mode: int | None = None,
    private_key: Path | None = None,
) -> Path:
    """Copia el fixture válido Linux a ``tmp_path`` con ``work_dir`` controlado.

    ``mode`` y ``private_key`` (Item 006) permiten fijar permisos del JSON y
    una clave privada local para que los casos de validación de entorno sean
    deterministas y no dependan de archivos del desarrollador.
    """
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(work_dir if work_dir is not None else tmp_path / "work")
    if private_key is not None:
        data["servers"][1]["auth"]["private_key"] = str(private_key)
    if mutate is not None:
        mutate(data)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return path


def _key(tmp_path: Path, *, name: str = "id_test", mode: int = 0o600) -> Path:
    """Crea una clave privada ficticia usable por los tests de validación."""
    key = tmp_path / name
    key.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nZmljdGljaWE=\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    key.chmod(mode)
    return key


# --- validate exitoso ---


def test_validate_config_flag_exits_0_with_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Configuración válida" in out
    assert str(config_path) in out
    assert "bases: 1" in out
    assert "servidores SFTP: 2" in out


def test_validate_creates_log_file_with_validation_line(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    assert "Configuración válida" in content
    assert "masterkey" not in content


def test_validate_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv(ENV_CONFIG_VAR, str(config_path))
    assert main(["validate"]) == EXIT_OK


def test_config_flag_takes_precedence_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv(ENV_CONFIG_VAR, str(tmp_path / "inexistente.json"))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK


def test_setup_logging_failure_still_exits_0_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def logging_roto(config: Any) -> Any:
        raise OSError(13, "el directorio de logs no es creable")

    monkeypatch.setattr("odin.cli.setup_logging", logging_roto)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Configuración válida" in captured.out
    assert "Advertencia" in captured.err


# --- exit 2: resolución de la ruta de configuración ---


def test_missing_config_source_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--config" in err
    assert ENV_CONFIG_VAR in err


def test_blank_env_var_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ENV_CONFIG_VAR, "   ")
    assert main(["validate"]) == EXIT_CONFIG
    assert "--config" in capsys.readouterr().err


# --- exit 2: errores de configuración ---


def test_nonexistent_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inexistente = tmp_path / "no-existe.json"
    assert main(["validate", "--config", str(inexistente)]) == EXIT_CONFIG
    assert "no se pudo leer" in capsys.readouterr().err


def test_malformed_json_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    roto = tmp_path / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    assert main(["validate", "--config", str(roto)]) == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err


def test_structural_problem_exits_2_with_field_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vacio = tmp_path / "vacio.json"
    vacio.write_text("{}", encoding="utf-8")
    assert main(["validate", "--config", str(vacio)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "config.databases" in err
    assert "config.servers" in err


def test_semantic_problem_duplicate_database_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def duplicar(data: dict[str, Any]) -> None:
        data["databases"].append(dict(data["databases"][0]))

    config_path = _write_config(tmp_path, mutate=duplicar)
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "nombre duplicado" in err
    assert "config.databases[1].name" in err


# --- exit 1: error interno inesperado ---


def test_unexpected_exception_exits_1_with_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def explota(path: Any) -> Any:
        raise RuntimeError("falla interna simulada")

    monkeypatch.setattr("odin.cli.load_config", explota)
    assert main(["validate", "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "Error interno inesperado" in err
    assert "falla interna simulada" in err
    assert "Traceback (most recent call last)" in err


# --- ayuda y uso ---


def test_no_args_prints_help_listing_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "usage: odin" in out
    assert "validate" in out
    assert "run" in out


def test_unknown_subcommand_raises_systemexit_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["volar"])
    assert excinfo.value.code == EXIT_CONFIG


def test_exit_code_constants_follow_convention() -> None:
    assert (EXIT_OK, EXIT_INTERNAL, EXIT_CONFIG, EXIT_PARTIAL, EXIT_FAILURE) == (0, 1, 2, 3, 4)


# --- Item 006: validación completa (entorno, reporte y --strict) ---


def test_validate_help_lists_strict_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["validate", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--strict" in out
    assert "--config" in out


def test_validate_reports_warnings_and_still_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "ADVERTENCIAS (1):" in captured.out
    assert "permisos 644" in captured.out
    assert "VERIFICACIONES" in captured.out
    assert "Configuración válida" in captured.out
    assert "1 advertencia(s)" in captured.out
    # stderr solo recibe el log (handler de consola del Item 004), no errores del reporte
    assert "ERRORES" not in captured.err
    assert "Configuración inválida" not in captured.err
    assert "Configuración válida con advertencias" in captured.err


def test_validate_environment_error_exits_2_with_errors_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    config_path = _write_config(tmp_path, work_dir=archivo, mode=0o600, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "ERRORES (1):" in captured.err
    assert "config.local.work_dir" in captured.err
    assert "Configuración inválida" in captured.err
    assert "ERRORES" not in captured.out
    assert "VERIFICACIONES" in captured.out


def test_validate_strict_promotes_warnings_to_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path), "--strict"]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "--strict" in captured.err
    assert "tratadas como errores" in captured.err
    assert "ADVERTENCIAS (1):" in captured.out


def test_validate_strict_exits_0_when_no_warnings(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    config_path = _write_config(tmp_path, work_dir=work_dir, mode=0o600, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path), "--strict"]) == EXIT_OK


def test_missing_private_key_is_warning_and_keeps_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o600, private_key=tmp_path / "clave-inexistente")
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "config.servers[1].auth.private_key" in out
    assert "no existe" in out


def test_missing_work_dir_is_reported_before_logging_creates_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work_dir = tmp_path / "work"
    config_path = _write_config(tmp_path, work_dir=work_dir, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "se creará en la primera ejecución" in out
    assert (work_dir / "logs").is_dir()


def test_parse_error_reports_skipped_environment_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vacio = tmp_path / "vacio.json"
    vacio.write_text("{}", encoding="utf-8")
    assert main(["validate", "--config", str(vacio)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "ERRORES (4):" in err
    assert "No se ejecutaron las verificaciones de entorno" in err
    assert "Configuración inválida" in err


def test_windows_flavored_config_exits_0_on_any_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data: dict[str, Any] = json.loads(WINDOWS_FIXTURE.read_text(encoding="utf-8"))
    data["servers"][1]["auth"]["private_key"] = str(_key(tmp_path))
    config_path = tmp_path / "config.windows.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config_path.chmod(0o600)
    # En POSIX el work_dir con sabor Windows ("D:\Backups\odin") es una ruta relativa,
    # así que setup_logging crearía un directorio literal respecto del CWD: se cambia a
    # tmp_path para no ensuciar el repositorio.
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    if sys.platform != "win32":
        assert "verificación omitida" in out
        assert "sabor Windows" in out


def test_findings_are_logged_with_counts_and_without_secrets(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    config_path = _write_config(tmp_path, work_dir=work_dir, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    content = log_path.read_text(encoding="utf-8")
    assert "Configuración válida con advertencias" in content
    assert "errores: 0 | advertencias: 1" in content
    assert "config: el archivo de configuración tiene permisos 644" in content
    for secreto in ("masterkey", "remote-secret-1", "smtp-secret"):
        assert secreto not in content


def test_error_findings_are_logged_at_error_level(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    log_dir = tmp_path / "logs"
    config_path = _write_config(
        tmp_path,
        work_dir=archivo,
        mode=0o600,
        private_key=_key(tmp_path),
        mutate=lambda data: data["local"].update(log_dir=str(log_dir)),
    )
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    content = (log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Configuración inválida" in content
    assert "ERROR" in content
    assert "config.local.work_dir" in content


# --- Item 019: subcomando run (fase de respaldo, exit codes 0/3/4) ---

PAYLOAD = b"ODIN backup payload " * 64


def _result(name: str, success: bool, work_dir: Path) -> BackupResult:
    """Resultado de respaldo; los exitosos escriben un ``.fbk`` real.

    La CLI ahora comprime cada respaldo exitoso (Item 025), así que la ruta
    debe existir en el ``work_dir`` temporal para que la fase de compresión
    real culmine.
    """
    if success:
        backup_path = work_dir / f"{name}.fbk"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(PAYLOAD)
        return BackupResult(
            success=True,
            database_name=name,
            backup_path=backup_path,
            file_size_bytes=len(PAYLOAD),
            duration_seconds=0.1,
        )
    return BackupResult(
        success=False,
        database_name=name,
        duration_seconds=0.1,
        error_message="gbak falló (código 1): database is in use",
    )


def _install_fake_notifier(
    monkeypatch: pytest.MonkeyPatch,
    outcome: Callable[[ReportMessage], NotificationResult] | None = None,
) -> None:
    """Reemplaza ``EmailNotifier`` en el pipeline: éxito sin SMTP real por default.

    Desde el Item 043 el pipeline envía el correo al final de cada corrida;
    este doble evita conexiones reales y ``outcome`` permite forzar el
    desenlace del envío (Item 044: SMTP caído).
    """

    class FakeEmailNotifier:
        def __init__(self, smtp: Any = None, to: str = "", from_: str = "") -> None:
            self.smtp = smtp
            self.to = to
            self.from_ = from_

        @classmethod
        def from_config(cls, config: Any) -> FakeEmailNotifier:
            return cls(
                smtp=config.notification.smtp,
                to=config.notification.to,
                from_=config.notification.from_,
            )

        def send(self, report: ReportMessage) -> NotificationResult:
            if outcome is not None:
                return outcome(report)
            return NotificationResult(success=True, recipient=self.to, duration_seconds=0.01)

    monkeypatch.setattr("odin.pipeline.EmailNotifier", FakeEmailNotifier)


def _install_fake_retention(
    monkeypatch: pytest.MonkeyPatch, result: RetentionResult | None = None
) -> None:
    """Reemplaza ``RetentionExecutor`` en el pipeline por un doble sin disco.

    Desde el Item 046 el pipeline aplica la retención al final de cada
    corrida; el doble evita tocar el ``work_dir`` real y ``result`` permite
    fijar el desenlace (eliminados, deshabilitada, errores).
    """

    class FakeRetentionExecutor:
        def run_retention(self, work_dir: Any, retention_days: int) -> RetentionResult:
            if result is not None:
                return result
            return RetentionResult(enabled=retention_days > 0)

    monkeypatch.setattr("odin.pipeline.RetentionExecutor", FakeRetentionExecutor)


def _install_fake_executor(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[list[Any], Path], BatchBackupResult],
) -> None:
    """Reemplaza ``BackupExecutor`` en la CLI por un lote controlado.

    Desde el Item 035 la CLI delega en ``odin.pipeline.run_pipeline``, así
    que el doble se instala en ``odin.pipeline``. El ``TransferExecutor``, el
    ``EmailNotifier`` y el ``RetentionExecutor`` también se doblan (éxito
    silencioso) para que los tests de respaldo/compresión no intenten
    conexiones SFTP/SMTP reales ni toquen archivos del ``work_dir``.
    """

    class FakeBackupExecutor:
        def __init__(self, gbak_path: Any = None, timeout: Any = None) -> None:
            self.gbak_path = gbak_path
            self.timeout = timeout

        def run_batch_backup(self, databases: list[Any], work_dir: Path) -> BatchBackupResult:
            return builder(databases, work_dir)

    monkeypatch.setattr("odin.pipeline.BackupExecutor", FakeBackupExecutor)
    _install_fake_transfer(monkeypatch)
    _install_fake_notifier(monkeypatch)
    _install_fake_retention(monkeypatch)


def _install_fake_transfer(
    monkeypatch: pytest.MonkeyPatch,
    results: Callable[[Sequence[Any], Path], Sequence[TransferResult]] | None = None,
) -> None:
    """Reemplaza ``TransferExecutor`` en el pipeline por un doble controlable.

    Sin ``results``, cada servidor devuelve un ``TransferResult`` exitoso con
    el tamaño local verificado (el ``.fbk.7z`` real de los tests).
    """

    class FakeTransferExecutor:
        def run_batch_transfer(
            self, servers: Sequence[Any], local_path: Path
        ) -> list[TransferResult]:
            if results is not None:
                return list(results(servers, local_path))
            size = local_path.stat().st_size
            return [
                TransferResult(
                    success=True,
                    server_name=server.name,
                    local_path=Path(local_path),
                    remote_path=posixpath.join(server.remote_path, Path(local_path).name),
                    transferred_bytes=size,
                    duration_seconds=0.05,
                )
                for server in servers
            ]

    monkeypatch.setattr("odin.pipeline.TransferExecutor", FakeTransferExecutor)


def _with_second_database(data: dict[str, Any]) -> None:
    second = dict(data["databases"][0])
    second["name"] = "erp_secundaria"
    second["connection"] = "localhost/3050:/var/lib/firebird/data/erp2.fdb"
    data["databases"].append(second)


def test_run_all_success_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    work_dir = tmp_path / "work"

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.2,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Respaldo y compresión finalizados" in out
    assert "1/1 base(s) con éxito" in out
    assert "OK    erp_principal" in out
    assert str(work_dir / "erp_principal.fbk") in out
    assert str(work_dir / "erp_principal.fbk.7z") in out
    assert "→" in out
    assert "bytes" in out
    assert (work_dir / "erp_principal.fbk.7z").is_file()


def test_run_partial_failure_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mutate=_with_second_database)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        outcomes = [True, False]
        results = [
            _result(db.name, ok, work_dir)
            for db, ok in zip(databases, outcomes, strict=True)
        ]
        return BatchBackupResult(results=results, success=False, total_duration_seconds=0.3)

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_PARTIAL
    captured = capsys.readouterr()
    assert "1/2 base(s) con éxito" in captured.out
    assert "FALLO erp_secundaria" in captured.err


def test_run_total_failure_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, False, work_dir) for db in databases],
            success=False,
            total_duration_seconds=0.3,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    assert "0/1 base(s) con éxito" in capsys.readouterr().out


def test_run_compression_failure_with_successful_backup_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        # El respaldo "exitoso" apunta a un .fbk que no existe: la compresión falla.
        return BatchBackupResult(
            results=[
                BackupResult(
                    success=True,
                    database_name=db.name,
                    backup_path=work_dir / f"{db.name}.fbk",
                    file_size_bytes=10,
                    duration_seconds=0.1,
                )
                for db in databases
            ],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "0/1 base(s) con éxito" in captured.out
    assert "FALLO erp_principal" in captured.err
    assert "compresión fallida" in captured.err
    assert "no existe" in captured.err
    # el respaldo sí ocurrió: su ruta y tamaño quedan en el mensaje de fallo
    assert str(tmp_path / "work" / "erp_principal.fbk") in captured.err
    assert "10 bytes" in captured.err


def test_run_mixed_success_and_compression_failure_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mutate=_with_second_database)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        results = [
            _result("erp_principal", True, work_dir),
            BackupResult(
                success=True,
                database_name="erp_secundaria",
                backup_path=work_dir / "erp_secundaria.fbk",
                file_size_bytes=10,
                duration_seconds=0.1,
            ),
        ]
        return BatchBackupResult(results=results, success=True, total_duration_seconds=0.2)

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_PARTIAL
    captured = capsys.readouterr()
    assert "1/2 base(s) con éxito" in captured.out
    assert "FALLO erp_secundaria" in captured.err


def test_run_all_compressions_fail_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mutate=_with_second_database)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[
                BackupResult(
                    success=True,
                    database_name=db.name,
                    backup_path=work_dir / f"{db.name}.fbk",
                    file_size_bytes=10,
                    duration_seconds=0.1,
                )
                for db in databases
            ],
            success=True,
            total_duration_seconds=0.2,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "0/2 base(s) con éxito" in captured.out
    assert captured.err.count("compresión fallida") == 2


def test_run_encrypts_archives_when_password_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = "comp-prueba"
    config_path = _write_config(
        tmp_path,
        mutate=lambda data: data["compression"].update(password=password),
    )
    work_dir = tmp_path / "work"

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_OK

    archive = work_dir / "erp_principal.fbk.7z"
    assert archive.is_file()
    with pytest.raises(py7zr.PasswordRequired), py7zr.SevenZipFile(archive, "r") as sevenzip:
        sevenzip.extractall(path=tmp_path / "sin_clave")
    with py7zr.SevenZipFile(archive, "r", password=password) as sevenzip:
        sevenzip.extractall(path=tmp_path / "con_clave")
    assert (tmp_path / "con_clave" / "erp_principal.fbk").read_bytes() == PAYLOAD


def test_run_invalid_gbak_path_exits_4_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(
        tmp_path,
        mutate=lambda data: data["databases"][0].update(
            gbak_path=str(tmp_path / "no-existe" / "gbak")
        ),
    )
    _install_fake_notifier(monkeypatch)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "0/1 base(s) con éxito" in captured.out
    assert "no se pudo ejecutar gbak" in captured.err


def test_run_unusable_work_dir_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[],
            success=False,
            total_duration_seconds=0.0,
            error_message="no se pudo preparar el directorio de trabajo",
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    assert "Respaldo no ejecutado" in capsys.readouterr().err


def test_run_missing_config_source_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run"]) == EXIT_CONFIG
    assert "--config" in capsys.readouterr().err


def test_run_invalid_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    roto = tmp_path / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    assert main(["run", "--config", str(roto)]) == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err


def test_run_help_lists_config_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    assert "--config" in capsys.readouterr().out


# --- run con transferencia (Item 035) ---


def _install_failing_transfer(
    monkeypatch: pytest.MonkeyPatch,
    fail_for: Callable[[str], bool],
) -> None:
    """Transferencia doblada: falla los servidores de las bases indicadas."""

    def results(servers: Sequence[Any], local_path: Path) -> Sequence[TransferResult]:
        size = local_path.stat().st_size
        fails = fail_for(local_path.stem.replace(".fbk", ""))
        return [
            TransferResult(
                success=not fails,
                server_name=server.name,
                local_path=Path(local_path),
                remote_path=posixpath.join(server.remote_path, Path(local_path).name),
                transferred_bytes=None if fails else size,
                duration_seconds=0.05,
                error_message="Connection error: refused" if fails else None,
            )
            for server in servers
        ]

    _install_fake_transfer(monkeypatch, results)


def test_run_transfer_failure_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    _install_failing_transfer(monkeypatch, lambda name: True)

    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "0/1 base(s) con éxito" in captured.out
    assert "FALLO erp_principal" in captured.err
    assert "transferencia fallida" in captured.err
    assert "Connection error: refused" in captured.err


def test_run_partial_transfer_failure_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mutate=_with_second_database)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    _install_failing_transfer(monkeypatch, lambda name: name == "erp_principal")

    assert main(["run", "--config", str(config_path)]) == EXIT_PARTIAL
    captured = capsys.readouterr()
    assert "1/2 base(s) con éxito" in captured.out
    assert "FALLO erp_principal" in captured.err
    assert "OK    erp_secundaria" in captured.out


def test_run_transfer_success_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    assert "1/1 base(s) con éxito" in capsys.readouterr().out


def test_run_prints_transfer_summary_per_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Transferencia SFTP: 2/2 servidor(es) exitosos" in captured.out
    assert (
        "erp_principal → sitio-alterno-1: OK /backups/firebird/erp_principal.fbk.7z"
        in captured.out
    )
    assert (
        "erp_principal → sitio-alterno-2: OK /srv/backups/firebird/erp_principal.fbk.7z"
        in captured.out
    )
    assert "bytes" in captured.out


def test_run_prints_transfer_failures_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, True, work_dir) for db in databases],
            success=True,
            total_duration_seconds=0.1,
        )

    _install_fake_executor(monkeypatch, builder)
    _install_failing_transfer(monkeypatch, lambda name: True)
    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "Transferencia SFTP: 0/2 servidor(es) exitosos" in captured.out
    assert "erp_principal → sitio-alterno-1: FALLO (Connection error: refused)" in captured.err
    assert "erp_principal → sitio-alterno-2: FALLO (Connection error: refused)" in captured.err


# --- Exit codes finales y resumen de consola con el correo (Item 044) ---


def _successful_batch(databases: list[Any], work_dir: Path) -> BatchBackupResult:
    """Lote con todas las bases respaldadas y comprimidas con éxito."""
    return BatchBackupResult(
        results=[_result(db.name, True, work_dir) for db in databases],
        success=True,
        total_duration_seconds=0.1,
    )


def _notification_outcome(
    *, success: bool, message: str | None = None
) -> Callable[[ReportMessage], NotificationResult]:
    """Desenlace del envío a usar por el notifier doblado."""

    def outcome(report: ReportMessage) -> NotificationResult:
        return NotificationResult(
            success=success,
            recipient="control@example.com",
            duration_seconds=0.02,
            error_message=None if success else message,
        )

    return outcome


def test_run_success_prints_notification_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)

    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Correo enviado a control@example.com" in out


def test_run_notification_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_notifier(
        monkeypatch,
        _notification_outcome(success=False, message="SMTPConnectError: conexión rechazada"),
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_INTERNAL
    captured = capsys.readouterr()
    assert "1/1 base(s) con éxito" in captured.out
    assert "Correo NO enviado: SMTPConnectError: conexión rechazada" in captured.err


def test_run_partial_with_notification_failure_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mutate=_with_second_database)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[
                _result("erp_principal", True, work_dir),
                _result("erp_secundaria", False, work_dir),
            ],
            success=False,
            total_duration_seconds=0.2,
        )

    _install_fake_executor(monkeypatch, builder)
    _install_fake_notifier(
        monkeypatch, _notification_outcome(success=False, message="SMTP caído")
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_PARTIAL
    captured = capsys.readouterr()
    assert "1/2 base(s) con éxito" in captured.out
    assert "Correo NO enviado: SMTP caído" in captured.err


def test_run_total_failure_precedes_notification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def builder(databases: list[Any], work_dir: Path) -> BatchBackupResult:
        return BatchBackupResult(
            results=[_result(db.name, False, work_dir) for db in databases],
            success=False,
            total_duration_seconds=0.2,
        )

    _install_fake_executor(monkeypatch, builder)
    _install_fake_notifier(
        monkeypatch, _notification_outcome(success=False, message="SMTP caído")
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "0/1 base(s) con éxito" in captured.out
    assert "Correo NO enviado: SMTP caído" in captured.err


def test_run_masks_notification_error_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_notifier(
        monkeypatch,
        _notification_outcome(
            success=False, message="SMTPAuthenticationError: credencial masterkey rechazada"
        ),
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_INTERNAL
    captured = capsys.readouterr()
    assert "masterkey" not in captured.err
    assert "***" in captured.err
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    log = log_path.read_text(encoding="utf-8")
    assert "masterkey" not in log
    assert "Correo NO enviado" in log


def test_run_help_mentions_email(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    assert "correo" in capsys.readouterr().out.lower()


# --- Retención local en el resumen de la CLI (Item 046) ---


def test_run_prints_retention_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_retention(
        monkeypatch,
        RetentionResult(
            examined=3,
            deleted=2,
            freed_bytes=2 * 1024 * 1024,
            duration_seconds=0.01,
        ),
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Retención local: 2 archivo(s) eliminado(s), 2.0 MB liberados." in out
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    log = log_path.read_text(encoding="utf-8")
    assert "Retención local: 2/3 archivo(s) eliminados, 2097152 bytes liberados" in log


def test_run_prints_retention_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_retention(monkeypatch, RetentionResult(enabled=False))

    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    assert "Retención local: deshabilitada (retention_days=0)." in capsys.readouterr().out


def test_run_retention_errors_do_not_change_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_retention(
        monkeypatch,
        RetentionResult(
            examined=1,
            errors=(
                RetentionError(path="/work/vieja_20200101_000000.fbk", message="permiso denegado"),
            ),
        ),
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Correo enviado a control@example.com" in captured.out
    assert (
        "FALLO retención de /work/vieja_20200101_000000.fbk: permiso denegado"
        in captured.err
    )


def test_run_masks_retention_error_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_executor(monkeypatch, _successful_batch)
    _install_fake_retention(
        monkeypatch,
        RetentionResult(
            errors=(
                RetentionError(path="/work/vieja.fbk", message="acceso con masterkey denegado"),
            ),
        ),
    )

    assert main(["run", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "masterkey" not in captured.err
    assert "***" in captured.err
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    assert "masterkey" not in log_path.read_text(encoding="utf-8")


# --- Item 053: subcomando service (run en primer plano y status) ---

DEAD_PID = 2**31 - 1


class _FakeSchedulerService:
    """Doble de ``SchedulerService``: modela el bloqueo y la señal de parada."""

    def __init__(self, *, state_store: Any, raise_interrupt: bool) -> None:
        self.state_store = state_store
        self.raise_interrupt = raise_interrupt
        self.started = False
        self.shutdown_calls = 0

    def start(self) -> None:
        self.started = True
        if self.raise_interrupt:
            raise KeyboardInterrupt

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdown_calls += 1


def _install_fake_service(
    monkeypatch: pytest.MonkeyPatch, *, raise_interrupt: bool = True
) -> list[_FakeSchedulerService]:
    """Reemplaza la fábrica real del CLI por un doble que registra el estado."""
    created: list[_FakeSchedulerService] = []

    def factory(config: Config, *, state_store: SchedulerStateStore) -> Any:
        for index, job in enumerate(config.scheduler.jobs):
            state_store.register_job(f"job-{index}", job, next_fire_time=None)
        service = _FakeSchedulerService(
            state_store=state_store, raise_interrupt=raise_interrupt
        )
        created.append(service)
        return service

    monkeypatch.setattr("odin.cli._build_scheduler_service", factory)
    return created


def _write_service_state(config_path: Path, *, pid: int) -> Path:
    """Persiste un estado del servicio con un job y un ciclo exitoso."""
    config = load_config(config_path)
    store = SchedulerStateStore(
        state_path(config.local.work_dir),
        pid=pid,
        config_path=str(config.config_path),
        started_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
        clock=lambda: datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    )
    store.register_job(
        "job-0",
        config.scheduler.jobs[0],
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
    return store.save()


def test_service_without_action_exits_2_with_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["service"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    for action in ("run", "status", "reload", "install", "uninstall", "start", "stop"):
        assert action in err


def test_service_run_missing_config_source_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["service", "run"]) == EXIT_CONFIG
    assert "No se indicó el archivo de configuración" in capsys.readouterr().err


def test_service_run_disabled_scheduler_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(
        tmp_path, mutate=lambda data: data["scheduler"].update(enabled=False)
    )
    assert main(["service", "run", "--config", str(config_path)]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "deshabilitado" in captured.err
    assert not (tmp_path / "work" / "scheduler_state.json").exists()


def test_service_run_invalid_config_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(
        tmp_path, mutate=lambda data: data["scheduler"].update(jobs="no-es-lista")
    )
    assert main(["service", "run", "--config", str(config_path)]) == EXIT_CONFIG
    assert "scheduler.jobs" in capsys.readouterr().err


def test_service_run_starts_and_stops_on_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    created = _install_fake_service(monkeypatch, raise_interrupt=True)

    assert main(["service", "run", "--config", str(config_path)]) == EXIT_OK
    assert len(created) == 1
    service = created[0]
    assert service.started is True
    assert service.shutdown_calls == 1

    config = load_config(config_path)
    result = load_state(state_path(config.local.work_dir))
    assert result.state is not None
    assert result.state.pid == os.getpid()
    assert [job.job_id for job in result.state.jobs] == ["job-0"]
    assert "en primer plano" in (
        config.local.resolved_log_dir / LOG_FILENAME
    ).read_text(encoding="utf-8")


def test_service_run_persists_state_when_start_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    created = _install_fake_service(monkeypatch, raise_interrupt=False)

    assert main(["service", "run", "--config", str(config_path)]) == EXIT_OK
    assert created[0].started is True
    assert created[0].shutdown_calls == 1
    state_file = load_config(config_path).local.work_dir / "scheduler_state.json"
    assert state_file.exists()


def test_service_run_internal_error_still_shuts_down_and_saves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    class FailingService:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def start(self) -> None:
            raise RuntimeError("fallo inesperado del executor")

        def shutdown(self, *, wait: bool = True) -> None:
            self.shutdown_calls += 1

    service = FailingService()

    def factory(config: Config, *, state_store: SchedulerStateStore) -> Any:
        state_store.register_job("job-0", config.scheduler.jobs[0])
        return service

    monkeypatch.setattr("odin.cli._build_scheduler_service", factory)

    assert main(["service", "run", "--config", str(config_path)]) == EXIT_INTERNAL
    assert service.shutdown_calls == 1
    state_file = load_config(config_path).local.work_dir / "scheduler_state.json"
    assert state_file.exists()
    assert "Error interno inesperado" in capsys.readouterr().err


def test_stop_signals_installs_and_restores_handlers() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    with _stop_signals():
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) is previous


def test_service_status_renders_running_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert f"Servicio ODIN: en ejecución (pid {os.getpid()})" in out
    assert "job-0 [erp_principal] schedule '0 2 * * *'" in out
    assert "Próximo disparo: 2026-09-17T02:00:00+00:00" in out
    assert "Último ciclo: success en 1.2 s (erp_principal; correo enviado)" in out
    assert "Salud: OK" in out


def test_service_status_reports_stale_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("la vigencia del pid no se verifica en Windows")
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=DEAD_PID)

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert f"Servicio ODIN: detenido (pid {DEAD_PID} ya no está en ejecución)" in out
    assert "job-0" in out


def test_service_status_without_state_reports_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Servicio ODIN: sin estado" in out
    assert "Motivo:" in out


def test_service_status_missing_config_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["service", "status"]) == EXIT_CONFIG
    assert "No se indicó el archivo de configuración" in capsys.readouterr().err


# --- Item 055: service reload (recarga en caliente) ---


HAS_SIGUSR1 = hasattr(signal, "SIGUSR1")


class _FakeReloadService:
    """Doble mínimo para el handler de SIGUSR1: cuenta solicitudes."""

    def __init__(self) -> None:
        self.reload_requests = 0

    def request_reload(self) -> None:
        self.reload_requests += 1


def test_service_reload_without_running_service_reports_clear_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    assert main(["service", "reload", "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "No hay servicio en ejecución" in err
    assert "no existe el archivo de estado" in err


def test_service_reload_stale_state_reports_clear_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("la vigencia del pid no se verifica en Windows")
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=DEAD_PID)
    assert main(["service", "reload", "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "No hay servicio en ejecución" in err
    assert f"pid {DEAD_PID}" in err


def test_service_reload_sends_sigusr1_to_running_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if not HAS_SIGUSR1:
        pytest.skip("la plataforma no tiene SIGUSR1")
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())
    kills: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))

    monkeypatch.setattr(os, "kill", fake_kill)

    assert main(["service", "reload", "--config", str(config_path)]) == EXIT_OK
    assert kills == [(os.getpid(), 0), (os.getpid(), signal.SIGUSR1)]
    assert "SIGUSR1" in capsys.readouterr().out


def test_service_reload_writes_control_file_without_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())
    monkeypatch.setattr("odin.cli._RELOAD_VIA_SIGNAL", False)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))

    assert main(["service", "reload", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    work_dir = load_config(config_path).local.work_dir
    request_path = work_dir / RELOAD_REQUEST_FILENAME
    assert request_path.exists()
    assert "archivo de control" in out
    assert all(sig != signal.SIGUSR1 for _, sig in kills)


def test_service_reload_invalid_config_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text("{esto no es json", encoding="utf-8")
    assert main(["service", "reload", "--config", str(config_path)]) == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err


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


# --- Item 062: service install|uninstall|start|stop ---


class _FakeServiceManager:
    """Gestor doble: registra specs/acciones y puede fallar a voluntad."""

    manager = ServiceManagerKind.SYSTEMD

    def __init__(
        self,
        config_path: Path | str,
        *,
        error: Exception | None = None,
        status: ServiceStatus | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.error = error
        self.status_result = status
        self.installed_specs: list[ServiceSpec] = []
        self.calls: list[str] = []

    def _fail_if_configured(self) -> None:
        if self.error is not None:
            raise self.error

    def install(self, spec: ServiceSpec) -> str:
        self._fail_if_configured()
        self.installed_specs.append(spec)
        return f"Servicio instalado: {spec.name}"

    def uninstall(self) -> str:
        self._fail_if_configured()
        self.calls.append("uninstall")
        return "Servicio desinstalado (odin)."

    def start(self) -> str:
        self._fail_if_configured()
        self.calls.append("start")
        return "Servicio arrancado (odin)."

    def stop(self) -> str:
        self._fail_if_configured()
        self.calls.append("stop")
        return "Servicio detenido (odin)."

    def status(self) -> ServiceStatus:
        self._fail_if_configured()
        if self.status_result is not None:
            return self.status_result
        return ServiceStatus.not_installed(self.manager)


def _install_fake_manager(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: Exception | None = None,
    status: ServiceStatus | None = None,
) -> list[_FakeServiceManager]:
    """Reemplaza el gestor real del CLI por dobles que registran su uso."""
    created: list[_FakeServiceManager] = []

    def factory(config_path: Path | str, **kwargs: Any) -> _FakeServiceManager:
        manager = _FakeServiceManager(config_path, error=error, status=status)
        created.append(manager)
        return manager

    monkeypatch.setattr("odin.cli.create_service_manager", factory)
    return created


def test_service_install_missing_config_exits_2_without_manager(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created = _install_fake_manager(monkeypatch)
    assert main(["service", "install"]) == EXIT_CONFIG
    assert "No se indicó el archivo de configuración" in capsys.readouterr().err
    assert created == []


def test_service_install_invalid_config_exits_2_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text("{esto no es json", encoding="utf-8")
    created = _install_fake_manager(monkeypatch)

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err
    assert created == []


def test_service_install_environment_errors_exit_2_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "no-es-directorio"
    blocker.write_text("archivo regular", encoding="utf-8")
    config_path = _write_config(tmp_path, work_dir=blocker)
    created = _install_fake_manager(monkeypatch)

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_CONFIG
    assert "config.local.work_dir" in capsys.readouterr().err
    assert created == []


def test_service_install_passes_absolute_spec_and_prints_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    executable = tmp_path / "bin" / "odin"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("odin.cli._service_executable", lambda: str(executable))
    created = _install_fake_manager(monkeypatch)

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    manager = created[0]
    assert manager.config_path == config_path.absolute()
    spec = manager.installed_specs[0]
    assert spec.config_path == config_path.absolute()
    assert spec.config_path.is_absolute()
    assert spec.executable == str(executable)
    assert "Servicio instalado: odin" in out
    assert "odin service start" in out
    assert "systemctl" in out


def test_service_install_manager_error_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    created = _install_fake_manager(monkeypatch, error=ServiceError("systemctl no disponible"))

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "No se pudo instalar el servicio" in err
    assert "systemctl no disponible" in err
    assert created[0].installed_specs == []


def test_service_install_unsupported_platform_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def factory(config_path: Path | str, **kwargs: Any) -> None:
        raise ServiceUnsupportedError("plataforma no soportada por el modo servicio")

    monkeypatch.setattr("odin.cli.create_service_manager", factory)

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_INTERNAL
    assert "plataforma no soportada" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ("uninstall", "Servicio desinstalado (odin)."),
        ("start", "Servicio arrancado (odin)."),
        ("stop", "Servicio detenido (odin)."),
    ],
)
def test_service_lifecycle_returns_0_and_prints_manager_message(
    action: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path)
    created = _install_fake_manager(monkeypatch)

    assert main(["service", action, "--config", str(config_path)]) == EXIT_OK
    assert message in capsys.readouterr().out
    assert created[0].calls == [action]
    assert created[0].config_path == config_path.absolute()


def test_service_lifecycle_without_config_uses_absolute_placeholder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created = _install_fake_manager(monkeypatch)

    assert main(["service", "stop"]) == EXIT_OK
    assert "Servicio detenido" in capsys.readouterr().out
    assert created[0].config_path.is_absolute()


@pytest.mark.parametrize("action", ["uninstall", "start", "stop"])
def test_service_lifecycle_manager_error_exits_1(
    action: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_manager(monkeypatch, error=ServiceError("operación no disponible"))

    assert main(["service", action, "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "No se pudo" in err
    assert "operación no disponible" in err


def test_service_executable_prefers_existing_argv0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "odin"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(executable)])
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/odin")
    assert _service_executable() == str(executable.resolve())


def test_service_executable_falls_back_to_path_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "odin"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["odin-inexistente"])
    monkeypatch.setattr(shutil, "which", lambda name: str(executable))
    assert _service_executable() == str(executable.resolve())


def test_service_executable_last_resort_is_bare_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [])
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _service_executable() == "odin"


def test_service_help_lists_lifecycle_actions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["service", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for action in ("install", "uninstall", "start", "stop"):
        assert action in out


# --- Item 063: service status completo (gestor del SO + scheduler) ---


def test_service_status_composes_platform_and_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())
    _install_fake_manager(
        monkeypatch,
        status=ServiceStatus(
            installed=True,
            running=True,
            auto_start=True,
            restart_on_failure=True,
            manager=ServiceManagerKind.SYSTEMD,
            detail="LoadState=loaded, ActiveState=active",
        ),
    )

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Servicio del SO (systemd): en ejecución" in out
    assert "Arranque automático: sí" in out
    assert "Reinicio ante caída: sí" in out
    assert "Detalle: LoadState=loaded, ActiveState=active" in out
    assert "Scheduler:" in out
    assert "Servicio ODIN: en ejecución (pid " in out
    assert "job-0 [erp_principal] schedule '0 2 * * *'" in out
    assert "masterkey" not in out
    assert "remote-secret-1" not in out
    assert "smtp-secret" not in out


def test_service_status_not_installed_suggests_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _install_fake_manager(
        monkeypatch,
        status=ServiceStatus.not_installed(
            ServiceManagerKind.SYSTEMD, detail="LoadState=not-found"
        ),
    )

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Servicio del SO (systemd): no instalado" in out
    assert "odin service install" in out
    assert "Servicio ODIN: sin estado" in out


def test_service_status_stopped_platform_suggests_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())
    _install_fake_manager(
        monkeypatch,
        status=ServiceStatus(
            installed=True,
            running=False,
            auto_start=True,
            restart_on_failure=False,
            manager=ServiceManagerKind.SYSTEMD,
        ),
    )

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "instalado y detenido" in out
    assert "odin service start" in out
    assert "Servicio ODIN: en ejecución" in out


def test_service_status_running_platform_with_stale_state_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("la vigencia del pid no se verifica en Windows")
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=DEAD_PID)
    _install_fake_manager(
        monkeypatch,
        status=ServiceStatus(
            installed=True, running=True, manager=ServiceManagerKind.SYSTEMD
        ),
    )

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Servicio del SO (systemd): en ejecución" in out
    assert f"Servicio ODIN: detenido (pid {DEAD_PID} ya no está en ejecución)" in out


def test_service_status_manager_error_is_warning_with_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    _write_service_state(config_path, pid=os.getpid())
    _install_fake_manager(monkeypatch, error=ServiceError("systemctl no disponible"))

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "no se pudo consultar el gestor (systemctl no disponible)" in out
    assert "Servicio ODIN: en ejecución" in out


def test_service_status_manager_receives_absolute_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    created = _install_fake_manager(monkeypatch)

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    assert created[0].config_path == config_path.absolute()
