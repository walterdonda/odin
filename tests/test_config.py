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


def test_load_valid_linux_fixture() -> None:
    config = load_config(FIXTURES / "config_valid_linux.json")
    assert config.databases[0].name == "erp_principal"
    assert config.databases[0].charset == "ISO8859_1"
    assert config.servers[1].auth.method is AuthMethod.KEY
    assert config.scheduler.enabled is True


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
    assert config.local.min_free_mb == 1024
    assert config.local.sftp_retries == 3
    assert config.local.sftp_connect_timeout_sec == 30
    assert config.servers[0].host_key_policy is HostKeyPolicy.STRICT
    assert config.notification.log_tail_lines == 50
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
    assert any(
        p.field_path == "config.scheduler.jobs[0].databases[0]" for p in problems
    )


def test_schedule_must_have_five_fields(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["scheduler"]["jobs"][0]["schedule"] = "0 2 * *"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.scheduler.jobs[0].schedule" for p in problems)


def test_email_format(tmp_path: Path) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["notification"]["to"] = "no-es-un-email"

    problems = _problems(tmp_path, _mutate(bad))
    assert any(p.field_path == "config.notification.to" for p in problems)


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


def test_aggregation_of_multiple_errors(tmp_path: Path) -> None:
    def many(d: dict[str, Any]) -> None:
        d["compression"]["level"] = 99
        d["servers"][0]["port"] = 0
        d["local"]["retention_days"] = -3

    problems = _problems(tmp_path, _mutate(many))
    paths = {p.field_path for p in problems}
    assert {"config.compression.level", "config.servers[0].port", "config.local.retention_days"} <= paths
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
