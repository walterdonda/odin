"""Tests de modelos de configuración y parseo del JSON (Item 002)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from odin.config import (
    AuthMethod,
    Config,
    ConfigError,
    DbEngine,
    HostKeyPolicy,
    LogLevel,
    MisfirePolicy,
    load_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _base_valid() -> dict[str, Any]:
    return {
        "databases": [
            {
                "name": "erp_principal",
                "type": "firebird",
                "connection": "localhost/3050:/var/lib/firebird/data/erp.fdb",
                "user": "SYSDBA",
                "password": "masterkey",
                "role": None,
                "charset": "ISO8859_1",
                "gbak_path": None,
            }
        ],
        "compression": {"level": 7, "password": None},
        "servers": [
            {
                "name": "sitio-alterno-1",
                "host": "203.0.113.10",
                "port": 22,
                "username": "odin",
                "auth": {"method": "password", "password": "remote-secret"},
                "remote_path": "/backups/firebird/",
            }
        ],
        "notification": {
            "to": "control@example.com",
            "from": "odin-backups@example.com",
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "starttls": True,
                "username": "odin-backups@example.com",
                "password": "smtp-secret",
            },
        },
        "local": {"work_dir": "/var/backups/odin", "retention_days": 7},
        "scheduler": {
            "enabled": True,
            "timezone": "UTC",
            "jobs": [
                {
                    "databases": ["erp_principal"],
                    "schedule": "0 2 * * *",
                    "on_misfire": "run_once",
                    "skip_if_running": True,
                }
            ],
        },
    }


def _write(tmp_path: Path, data: dict[str, Any] | str) -> Path:
    p = tmp_path / "config.json"
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _load(tmp_path: Path, data: dict[str, Any]) -> Config:
    return load_config(_write(tmp_path, data))


def _problems(tmp_path: Path, data: dict[str, Any] | str) -> list:
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, data))
    return excinfo.value.problems


def _mutate(modifier) -> dict[str, Any]:
    data = _base_valid()
    modifier(data)
    return data


def _base_valid_postgres() -> dict[str, Any]:
    data = _base_valid()
    data["databases"][0] = {
        "name": "erp_principal",
        "type": "postgresql",
        "host": "db.example.com",
        "port": 5433,
        "dbname": "erp",
        "user": "odin_backup",
        "password": "s3cret",
        "pg_dump_path": None,
        "pg_dump_timeout_sec": None,
    }
    return data


def _mutate_pg(modifier) -> dict[str, Any]:
    data = _base_valid_postgres()
    modifier(data)
    return data


def test_load_valid_linux_fixture() -> None:
    config = load_config(FIXTURES / "config_valid_linux.json")
    assert config.databases[0].name == "erp_principal"
    assert config.databases[0].type is DbEngine.FIREBIRD
    assert config.databases[0].charset == "ISO8859_1"
    assert config.servers[1].auth.method is AuthMethod.KEY
    assert config.scheduler.enabled is True
    assert config.scheduler.jobs[0].on_misfire is MisfirePolicy.RUN_ONCE


def test_load_valid_windows_fixture() -> None:
    config = load_config(FIXTURES / "config_valid_windows.json")
    assert "erp.fdb" in config.databases[0].connection
    assert config.local.retention_days == 7


def test_minimal_config_applies_defaults(tmp_path: Path) -> None:
    data = _mutate(lambda d: (d.pop("compression"), d.pop("scheduler")))
    config = _load(tmp_path, data)
    assert config.compression.level == 7
    assert config.compression.password is None
    assert config.scheduler.enabled is False
    assert config.scheduler.timezone == "UTC"
    assert config.scheduler.jobs == []
    assert config.local.log_level is LogLevel.INFO
    assert config.local.gbak_timeout_sec == 7200
    assert config.local.pg_dump_timeout_sec == 7200
    assert config.local.min_free_mb == 1024
    assert config.local.sftp_retries == 3
    assert config.local.sftp_connect_timeout_sec == 30
    assert config.servers[0].host_key_policy is HostKeyPolicy.STRICT
    assert config.notification.log_tail_lines == 200
    assert config.notification.contact is None
    assert config.notification.subject is None
    assert config.notification.body_text is None
    assert config.notification.body_html is None
    assert config.notification.signature is None
    assert config.environment is None
    assert config.local.resolved_log_dir == config.local.work_dir / "logs"


def test_malformed_json_reports_line_and_column(tmp_path: Path) -> None:
    problems = _problems(tmp_path, '{"databases": [')
    assert len(problems) == 1
    assert "línea" in problems[0].message
    assert "columna" in problems[0].message


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "no-existe.json")
    assert "no se pudo leer" in excinfo.value.problems[0].message


def test_root_must_be_object(tmp_path: Path) -> None:
    problems = _problems(tmp_path, "[1, 2, 3]")
    assert problems[0].field_path == "config"
    assert "objeto JSON" in problems[0].message


def test_unknown_field_with_suggestion(tmp_path: Path) -> None:
    def typo(d: dict[str, Any]) -> None:
        d["databases"][0]["pasword"] = "otro"

    problems = _problems(tmp_path, _mutate(typo))
    assert any("pasword" in p.field_path for p in problems)
    assert any("password" in p.message and "quiso decir" in p.message for p in problems)


def test_unknown_top_level_field(tmp_path: Path) -> None:
    def extra(d: dict[str, Any]) -> None:
        d["servidores"] = []

    problems = _problems(tmp_path, _mutate(extra))
    assert any(p.field_path == "config.servidores" for p in problems)


def test_compression_level_out_of_range(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["compression"]["level"] = 10

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.compression.level" for p in problems)


def test_server_port_out_of_range(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["port"] = 70000

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].port" for p in problems)


def test_gbak_timeout_must_be_positive(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["local"]["gbak_timeout_sec"] = 0

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.local.gbak_timeout_sec" for p in problems)


def test_retention_days_non_negative(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["local"]["retention_days"] = -1

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.local.retention_days" for p in problems)


def test_min_free_mb_non_negative(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["local"]["min_free_mb"] = -5

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.local.min_free_mb" for p in problems)


def test_log_level_enum(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["local"]["log_level"] = "TRACE"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.local.log_level" for p in problems)
    assert any("TRACE" in p.message for p in problems)


def test_host_key_policy_enum(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["host_key_policy"] = "yolo"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].host_key_policy" for p in problems)


def test_auth_method_enum(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["auth"]["method"] = "token"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].auth.method" for p in problems)


def test_auth_password_requires_password(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["auth"] = {"method": "password"}

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].auth.password" for p in problems)


def test_auth_key_requires_private_key(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["auth"] = {"method": "key"}

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].auth.private_key" for p in problems)


def test_auth_password_method_rejects_private_key(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["auth"] = {
            "method": "password",
            "password": "x",
            "private_key": "~/.ssh/id_ed25519",
        }

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.servers[0].auth.private_key" for p in problems)


def test_duplicate_database_names(tmp_path: Path) -> None:
    def dup(d: dict[str, Any]) -> None:
        d["databases"].append(copy.deepcopy(d["databases"][0]))

    problems = _problems(tmp_path, _mutate(dup))
    assert any("duplicado" in p.message and "databases[1].name" in p.field_path for p in problems)


def test_duplicate_server_names(tmp_path: Path) -> None:
    def dup(d: dict[str, Any]) -> None:
        d["servers"].append(copy.deepcopy(d["servers"][0]))

    problems = _problems(tmp_path, _mutate(dup))
    assert any("duplicado" in p.message and "servers[1].name" in p.field_path for p in problems)


def test_job_references_existing_database(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["databases"] = ["inexistente"]

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.scheduler.jobs[0].databases[0]" for p in problems)


def test_schedule_must_have_five_fields(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["schedule"] = "0 2 * *"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.scheduler.jobs[0].schedule" for p in problems)


def test_schedule_out_of_range_reports_cron_error(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["schedule"] = "0 25 * * *"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.scheduler.jobs[0].schedule" and "cron" in p.message
        for p in problems
    )


def test_schedule_garbage_reports_cron_error(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["schedule"] = "not a cron"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.scheduler.jobs[0].schedule" and "cron" in p.message
        for p in problems
    )


def test_schedule_with_ranges_and_steps_is_valid(tmp_path: Path) -> None:
    def rich(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["schedule"] = "*/15 8-18 * * 1-5"

    config = _load(tmp_path, _mutate(rich))
    assert config.scheduler.jobs[0].schedule == "*/15 8-18 * * 1-5"


def test_invalid_timezone_and_cron_report_both_problems(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["timezone"] = "Marte/Olympus_Mons"
        d["scheduler"]["jobs"][0]["schedule"] = "0 25 * * *"

    problems = _problems(tmp_path, _mutate(bad))
    paths = {p.field_path for p in problems}
    assert "config.scheduler.timezone" in paths
    assert "config.scheduler.jobs[0].schedule" in paths


def test_email_format(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["notification"]["to"] = "no-es-un-email"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.notification.to" for p in problems)


def test_multiple_recipients_normalized(tmp_path: Path) -> None:
    def multiple(d: dict[str, Any]) -> None:
        d["notification"]["to"] = "control@example.com, ops@example.com"

    config = _load(tmp_path, _mutate(multiple))
    assert config.notification.to == "control@example.com, ops@example.com"


def test_multiple_recipients_with_spaces_normalized(tmp_path: Path) -> None:
    def multiple(d: dict[str, Any]) -> None:
        d["notification"]["to"] = "control@example.com , ops@example.com"

    config = _load(tmp_path, _mutate(multiple))
    assert config.notification.to == "control@example.com, ops@example.com"


def test_multiple_recipients_invalid_member_rejected(tmp_path: Path) -> None:
    def multiple(d: dict[str, Any]) -> None:
        d["notification"]["to"] = "control@example.com, no-es-un-email"

    problems = _problems(tmp_path, _mutate(multiple))
    assert any(
        p.field_path == "config.notification.to" and "no-es-un-email" in p.message
        for p in problems
    )


def test_notification_templates_parsed(tmp_path: Path) -> None:
    def templates(d: dict[str, Any]) -> None:
        d["environment"] = {"client": "caktus", "name": "prod"}
        d["notification"].update(
            {
                "contact": "ops@example.com",
                "subject": "[ODIN {entorno}] {estado} — {instancia}",
                "body_text": "{bases}\n{totales}",
                "body_html": "<pre>{log}</pre>",
                "signature": "ODIN · {cliente}",
                "log_tail_lines": 0,
            }
        )

    config = _load(tmp_path, _mutate(templates))
    assert config.notification.contact == "ops@example.com"
    assert config.notification.subject == "[ODIN {entorno}] {estado} — {instancia}"
    assert config.notification.body_text == "{bases}\n{totales}"
    assert config.notification.body_html == "<pre>{log}</pre>"
    assert config.notification.signature == "ODIN · {cliente}"
    assert config.notification.log_tail_lines == 0


def test_unknown_template_placeholder_rejected(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["notification"]["subject"] = "asunto {inventado}"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.notification.subject" and "inventado" in p.message
        for p in problems
    )


def test_stray_braces_in_template_rejected(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["notification"]["signature"] = "ODIN {cliente"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.notification.signature" and "llaves reservadas" in p.message
        for p in problems
    )


def test_template_requiring_environment_without_block_rejected(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["notification"]["subject"] = "[ODIN {cliente}] {estado}"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.notification.subject" and "environment" in p.message
        for p in problems
    )


def test_template_requiring_environment_with_block_parses(tmp_path: Path) -> None:
    def both(d: dict[str, Any]) -> None:
        d["environment"] = {"client": "caktus", "name": "prod"}
        d["notification"]["subject"] = "[ODIN {cliente}-{entorno}] {estado}"

    config = _load(tmp_path, _mutate(both))
    assert config.environment is not None
    assert config.environment.client == "caktus"
    assert config.environment.name == "prod"
    assert config.notification.subject == "[ODIN {cliente}-{entorno}] {estado}"


def test_environment_block_requires_client_and_name(tmp_path: Path) -> None:
    def partial(d: dict[str, Any]) -> None:
        d["environment"] = {"client": "caktus"}

    problems = _problems(tmp_path, _mutate(partial))
    assert any(p.field_path == "config.environment.name" for p in problems)


def test_environment_unknown_field_rejected(tmp_path: Path) -> None:
    def extra(d: dict[str, Any]) -> None:
        d["environment"] = {"client": "caktus", "name": "prod", "zone": "sur"}

    problems = _problems(tmp_path, _mutate(extra))
    assert any(p.field_path == "config.environment.zone" for p in problems)


def test_smtp_ssl_defaults_false(tmp_path: Path) -> None:
    config = _load(tmp_path, _base_valid())
    assert config.notification.smtp.ssl is False
    assert config.notification.smtp.starttls is True


def test_smtp_ssl_without_starttls_parses(tmp_path: Path) -> None:
    def implicit_ssl(d: dict[str, Any]) -> None:
        d["notification"]["smtp"].update({"starttls": False, "ssl": True})

    config = _load(tmp_path, _mutate(implicit_ssl))
    assert config.notification.smtp.ssl is True
    assert config.notification.smtp.starttls is False


def test_smtp_ssl_mutually_exclusive_with_starttls(tmp_path: Path) -> None:
    def both(d: dict[str, Any]) -> None:
        d["notification"]["smtp"]["ssl"] = True

    problems = _problems(tmp_path, _mutate(both))
    assert any(
        p.field_path == "config.notification.smtp.ssl" and "starttls" in p.message
        for p in problems
    )


def test_timezone_validated(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["timezone"] = "Marte/Olympus_Mons"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.scheduler.timezone" for p in problems)


def test_missing_required_field(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        del d["local"]["work_dir"]

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.local.work_dir" for p in problems)


def test_missing_required_section(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        del d["notification"]

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.notification" for p in problems)


def test_empty_databases_rejected(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["databases"] = []

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.databases" for p in problems)


def test_relative_paths_resolved_against_config_dir(tmp_path: Path) -> None:
    subdir = tmp_path / "config-dir"
    subdir.mkdir()

    def relative(d: dict[str, Any]) -> None:
        d["local"]["work_dir"] = "./work"
        d["local"]["log_dir"] = "logs"
        d["databases"][0]["gbak_path"] = "bin/gbak"

    config = _load(subdir, _mutate(relative))
    assert config.local.work_dir == subdir / "work"
    assert config.local.log_dir == subdir / "logs"
    assert config.databases[0].gbak_path == str(subdir / "bin" / "gbak")


def test_windows_style_work_dir_not_prefixed(tmp_path: Path) -> None:
    def windows(d: dict[str, Any]) -> None:
        d["local"]["work_dir"] = "D:\\Backups\\odin"

    config = _load(tmp_path, _mutate(windows))
    assert config.local.work_dir.as_posix() == "D:/Backups/odin"


def test_private_key_tilde_with_backslashes(tmp_path: Path) -> None:
    def key_auth(d: dict[str, Any]) -> None:
        d["servers"][0]["auth"] = {
            "method": "key",
            "private_key": "~\\.ssh\\id_ed25519",
        }

    config = _load(tmp_path, _mutate(key_auth))
    expected = (Path.home() / ".ssh" / "id_ed25519").as_posix()
    assert config.servers[0].auth.private_key is not None
    assert Path(config.servers[0].auth.private_key).as_posix() == expected


def test_gbak_path_relative_with_backslashes(tmp_path: Path) -> None:
    def gbak(d: dict[str, Any]) -> None:
        d["databases"][0]["gbak_path"] = "bin\\gbak.exe"

    config = _load(tmp_path, _mutate(gbak))
    assert config.databases[0].gbak_path is not None
    assert Path(config.databases[0].gbak_path).as_posix() == (tmp_path / "bin/gbak.exe").as_posix()


def test_relative_config_file_anchors_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def relative(d: dict[str, Any]) -> None:
        d["local"]["work_dir"] = "./work"

    config = load_config(_write(tmp_path, _mutate(relative)).name)
    assert config.local.work_dir == tmp_path / "work"


def test_aggregation_of_multiple_errors(tmp_path: Path) -> None:
    def many(d: dict[str, Any]) -> None:
        d["compression"]["level"] = 99
        d["servers"][0]["port"] = 0
        d["local"]["retention_days"] = -3

    problems = _problems(tmp_path, _mutate(many))
    paths = {p.field_path for p in problems}
    expected = {"config.compression.level", "config.servers[0].port", "config.local.retention_days"}
    assert expected <= paths
    assert len(problems) >= 3


def test_error_str_is_readable_multiline(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["compression"]["level"] = 99
        d["servers"][0]["port"] = 0

    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, _mutate(bad)))
    text = str(excinfo.value)
    assert "problema(s) de configuración" in text
    assert text.count("\n") >= 2


def test_iter_secret_fields(tmp_path: Path) -> None:
    def secrets(d: dict[str, Any]) -> None:
        d["compression"]["password"] = "comp-secret"
        d["servers"][0]["auth"] = {
            "method": "key",
            "private_key": "~/.ssh/id_ed25519",
            "passphrase": "pass-secret",
        }

    config = _load(tmp_path, _mutate(secrets))
    found = dict(config.iter_secret_fields())
    assert found["config.databases[0].password"] == "masterkey"
    assert found["config.compression.password"] == "comp-secret"
    assert found["config.servers[0].auth.passphrase"] == "pass-secret"
    assert "config.servers[0].auth.private_key" in found
    assert found["config.notification.smtp.password"] == "smtp-secret"
    assert len(found) == 5


def test_server_sftp_fields_parse_from_json(tmp_path: Path) -> None:
    def extra(d: dict[str, Any]) -> None:
        d["servers"][0].update(
            sftp_retries=5,
            sftp_connect_timeout_sec=11,
            sftp_operation_timeout_sec=22,
            sftp_retry_backoff_base=1.5,
            sftp_retry_max_delay_sec=12.0,
        )

    config = _load(tmp_path, _mutate(extra))
    server = config.servers[0]
    assert server.sftp_retries == 5
    assert server.sftp_connect_timeout_sec == 11
    assert server.sftp_operation_timeout_sec == 22
    assert server.sftp_retry_backoff_base == 1.5
    assert server.sftp_retry_max_delay_sec == 12.0


def test_server_sftp_fields_defaults(tmp_path: Path) -> None:
    config = _load(tmp_path, _base_valid())
    server = config.servers[0]
    assert server.sftp_retries == 3
    assert server.sftp_connect_timeout_sec == 30
    assert server.sftp_operation_timeout_sec == 60
    assert server.sftp_retry_backoff_base == 2.0
    assert server.sftp_retry_max_delay_sec == 30.0


def test_server_sftp_field_validation_errors(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["servers"][0]["sftp_retries"] = -1
        d["servers"][0]["sftp_connect_timeout_sec"] = "lento"
        d["servers"][0]["sftp_retry_backoff_base"] = True

    problems = _problems(tmp_path, _mutate(bad))
    paths = {p.field_path for p in problems}
    assert "config.servers[0].sftp_retries" in paths
    assert "config.servers[0].sftp_connect_timeout_sec" in paths
    assert "config.servers[0].sftp_retry_backoff_base" in paths


# --- type por entrada (dos motores) ---


def test_database_type_is_parsed(tmp_path: Path) -> None:
    config = _load(tmp_path, _base_valid())
    assert config.databases[0].type is DbEngine.FIREBIRD


def test_database_type_required(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        del d["databases"][0]["type"]

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.databases[0].type" and p.message == "campo requerido ausente"
        for p in problems
    )


def test_database_type_invalid_enum(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["databases"][0]["type"] = "oracle"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(
        p.field_path == "config.databases[0].type"
        and "valor inválido 'oracle'" in p.message
        and "firebird" in p.message
        and "postgresql" in p.message
        for p in problems
    )


# --- campos PostgreSQL ---


def test_postgresql_entry_parses_fields(tmp_path: Path) -> None:
    config = _load(tmp_path, _base_valid_postgres())
    db = config.databases[0]
    assert db.type is DbEngine.POSTGRESQL
    assert db.host == "db.example.com"
    assert db.port == 5433
    assert db.dbname == "erp"
    assert db.connection is None
    assert db.gbak_path is None
    assert db.gbak_timeout_sec is None
    assert db.pg_dump_path is None
    assert db.pg_dump_timeout_sec is None


def test_port_absent_or_null_parses_as_none(tmp_path: Path) -> None:
    def sin_port(d: dict[str, Any]) -> None:
        del d["databases"][0]["port"]

    config = _load(tmp_path, _mutate_pg(sin_port))
    assert config.databases[0].port is None

    def port_null(d: dict[str, Any]) -> None:
        d["databases"][0]["port"] = None

    config = _load(tmp_path, _mutate_pg(port_null))
    assert config.databases[0].port is None


def test_postgresql_port_bounds(tmp_path: Path) -> None:
    def muy_bajo(d: dict[str, Any]) -> None:
        d["databases"][0]["port"] = 0

    problems = _problems(tmp_path, _mutate_pg(muy_bajo))
    assert any(
        p.field_path == "config.databases[0].port" and ">= 1" in p.message for p in problems
    )

    def muy_alto(d: dict[str, Any]) -> None:
        d["databases"][0]["port"] = 65536

    problems = _problems(tmp_path, _mutate_pg(muy_alto))
    assert any(
        p.field_path == "config.databases[0].port" and "<= 65535" in p.message for p in problems
    )


def test_pg_dump_path_relative_with_backslashes(tmp_path: Path) -> None:
    def pg(d: dict[str, Any]) -> None:
        d["databases"][0]["pg_dump_path"] = "bin\\pg_dump.exe"

    config = _load(tmp_path, _mutate_pg(pg))
    assert config.databases[0].pg_dump_path is not None
    assert Path(config.databases[0].pg_dump_path).as_posix() == (
        tmp_path / "bin/pg_dump.exe"
    ).as_posix()


def test_pg_dump_timeout_must_be_positive(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["databases"][0]["pg_dump_timeout_sec"] = 0

    problems = _problems(tmp_path, _mutate_pg(bad))
    assert any(
        p.field_path == "config.databases[0].pg_dump_timeout_sec" and "> 0" in p.message
        for p in problems
    )


# --- checks condicionales por motor (_db_problems) ---


def test_firebird_connection_required_semantically(tmp_path: Path) -> None:
    def sin_conexion(d: dict[str, Any]) -> None:
        del d["databases"][0]["connection"]

    problems = _problems(tmp_path, _mutate(sin_conexion))
    assert any(
        p.field_path == "config.databases[0].connection"
        and p.message == "es requerido cuando type es 'firebird'"
        for p in problems
    )


def test_firebird_entry_rejects_postgresql_fields(tmp_path: Path) -> None:
    def intrusos(d: dict[str, Any]) -> None:
        d["databases"][0].update(host="db.example.com", port=5432, dbname="erp")

    problems = _problems(tmp_path, _mutate(intrusos))
    by_path = {p.field_path: p.message for p in problems}
    for field in ("host", "port", "dbname"):
        assert by_path.get(f"config.databases[0].{field}") == (
            "solo aplica cuando type es 'postgresql'"
        )


def test_firebird_entry_ignores_null_postgresql_fields(tmp_path: Path) -> None:
    def nulos(d: dict[str, Any]) -> None:
        d["databases"][0].update(host=None, port=None, dbname=None, pg_dump_path=None)

    config = _load(tmp_path, _mutate(nulos))
    assert config.databases[0].type is DbEngine.FIREBIRD


def test_postgresql_entry_requires_host_and_dbname(tmp_path: Path) -> None:
    def faltantes(d: dict[str, Any]) -> None:
        del d["databases"][0]["host"]
        del d["databases"][0]["dbname"]

    problems = _problems(tmp_path, _mutate_pg(faltantes))
    by_path = {p.field_path: p.message for p in problems}
    assert by_path.get("config.databases[0].host") == "es requerido cuando type es 'postgresql'"
    assert by_path.get("config.databases[0].dbname") == "es requerido cuando type es 'postgresql'"


def test_postgresql_entry_rejects_firebird_fields(tmp_path: Path) -> None:
    def intrusos(d: dict[str, Any]) -> None:
        d["databases"][0].update(
            connection="localhost:/var/lib/firebird/data/erp.fdb",
            role="RDB$ADMIN",
            charset="UTF8",
            gbak_path="/opt/firebird/bin/gbak",
            gbak_timeout_sec=60,
        )

    problems = _problems(tmp_path, _mutate_pg(intrusos))
    by_path = {p.field_path: p.message for p in problems}
    for field in ("connection", "role", "charset", "gbak_path", "gbak_timeout_sec"):
        assert by_path.get(f"config.databases[0].{field}") == (
            "solo aplica cuando type es 'firebird'"
        )


# --- local.pg_dump_timeout_sec ---


def test_local_pg_dump_timeout_defaults_to_7200(tmp_path: Path) -> None:
    config = _load(tmp_path, _base_valid())
    assert config.local.pg_dump_timeout_sec == 7200


def test_local_pg_dump_timeout_parses_and_must_be_positive(tmp_path: Path) -> None:
    def explicito(d: dict[str, Any]) -> None:
        d["local"]["pg_dump_timeout_sec"] = 3600

    config = _load(tmp_path, _mutate(explicito))
    assert config.local.pg_dump_timeout_sec == 3600

    def cero(d: dict[str, Any]) -> None:
        d["local"]["pg_dump_timeout_sec"] = 0

    problems = _problems(tmp_path, _mutate(cero))
    assert any(
        p.field_path == "config.local.pg_dump_timeout_sec" and "> 0" in p.message
        for p in problems
    )
