"""Tests de logging con rotación y enmascarado de secretos (Item 004)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

from odin.config import Config, load_config
from odin.log import (
    DEFAULT_BACKUP_COUNT,
    DEFAULT_MAX_BYTES,
    LOG_FILENAME,
    LOG_FORMAT,
    LOGGER_NAME,
    MIN_SECRET_LENGTH,
    MaskingFilter,
    SecretMasker,
    setup_logging,
)

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}")


@pytest.fixture()
def odin_logger() -> Iterator[logging.Logger]:
    """Devuelve el logger ``odin`` y lo limpia tras el test (sin handlers)."""
    logger = logging.getLogger(LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def _load_fixture_config(
    tmp_path: Path,
    *,
    work_dir: Path | None = None,
    log_level: str | None = None,
    log_dir: Path | None = None,
    compression_password: str | None = None,
) -> Config:
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(work_dir if work_dir is not None else tmp_path / "work")
    if log_level is not None:
        data["local"]["log_level"] = log_level
    if log_dir is not None:
        data["local"]["log_dir"] = str(log_dir)
    if compression_password is not None:
        data["compression"]["password"] = compression_password
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(config_path)


def _file_handler(logger: logging.Logger) -> RotatingFileHandler:
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    return handlers[0]


# --- SecretMasker (función pura) ---


def test_mask_single_secret() -> None:
    masker = SecretMasker(["hunter2pass"])
    assert masker.mask("conectando con password=hunter2pass ok") == "conectando con password=*** ok"


def test_mask_repeated_secret() -> None:
    masker = SecretMasker(["hunter2pass"])
    assert masker.mask("hunter2pass y otra vez hunter2pass") == "*** y otra vez ***"


def test_mask_multiple_secrets() -> None:
    masker = SecretMasker(["masterkey", "remote-secret-1"])
    masked = masker.mask("db=masterkey sftp=remote-secret-1")
    assert masked == "db=*** sftp=***"


def test_mask_empty_secret_ignored() -> None:
    masker = SecretMasker(["", "masterkey"])
    assert masker.secrets == ("masterkey",)
    assert masker.mask("texto sin secretos") == "texto sin secretos"
    assert masker.mask("usa masterkey") == "usa ***"


def test_mask_short_secret_ignored() -> None:
    masker = SecretMasker(["ab", "abc"])
    assert masker.secrets == ()
    assert masker.mask("ab y abc quedan intactos") == "ab y abc quedan intactos"
    assert MIN_SECRET_LENGTH == 4


def test_mask_longest_secret_first_avoids_partial_overlap() -> None:
    masker = SecretMasker(["abc123", "abc1234567"])
    assert masker.secrets == ("abc1234567", "abc123")
    assert masker.mask("clave abc1234567 fin") == "clave *** fin"


def test_mask_deduplicates_secrets() -> None:
    masker = SecretMasker(["masterkey", "masterkey", "remote-secret-1"])
    assert masker.secrets == ("remote-secret-1", "masterkey")


def test_mask_pem_block_body_removed() -> None:
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
        "BcMwggW7AgEAAoGBAKL0\n"
        "-----END PRIVATE KEY-----"
    )
    masker = SecretMasker([])
    masked = masker.mask(f"clave embebida:\n{pem}\nfin")
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" not in masked
    assert "-----BEGIN PRIVATE KEY-----" in masked
    assert "-----END PRIVATE KEY-----" in masked
    assert "***" in masked


def test_mask_pem_variants_openssh_and_encrypted() -> None:
    masker = SecretMasker([])
    openssh = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjE=\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    encrypted = (
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\nMIIFHDBOBgkq\n-----END ENCRYPTED PRIVATE KEY-----"
    )
    masked = masker.mask(f"{openssh}\n{encrypted}")
    assert "b3BlbnNzaC1rZXktdjE=" not in masked
    assert "MIIFHDBOBgkq" not in masked
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in masked
    assert "-----END ENCRYPTED PRIVATE KEY-----" in masked


def test_mask_unterminated_pem_block_masks_to_end() -> None:
    text = "dump truncado: -----BEGIN RSA PRIVATE KEY-----\nMIICXAIBAAKBgQDx resto del material"
    masker = SecretMasker([])
    masked = masker.mask(text)
    assert masked.startswith("dump truncado: -----BEGIN RSA PRIVATE KEY-----")
    assert "MIICXAIBAAKBgQDx" not in masked
    assert "resto del material" not in masked


def test_mask_text_without_secrets_unchanged() -> None:
    masker = SecretMasker(["masterkey", "remote-secret-1"])
    text = "odin: respaldo erp_principal completado en 12.3s (45.2 MiB)"
    assert masker.mask(text) == text


def test_masker_from_config_collects_fixture_secrets() -> None:
    config = load_config(LINUX_FIXTURE)
    masker = SecretMasker.from_config(config)
    assert "masterkey" in masker.secrets
    assert "remote-secret-1" in masker.secrets
    assert "smtp-secret" in masker.secrets


def test_masker_from_config_masks_fixture_secret() -> None:
    config = load_config(LINUX_FIXTURE)
    masker = SecretMasker.from_config(config)
    masked = masker.mask("gbak falló con password masterkey en erp_principal")
    assert "masterkey" not in masked
    assert "***" in masked


def test_masker_from_config_masks_compression_password(tmp_path: Path) -> None:
    config = _load_fixture_config(tmp_path, compression_password="comp-secret")

    masker = SecretMasker.from_config(config)

    assert "comp-secret" in masker.secrets
    masked = masker.mask("comprimiendo erp_principal con password comp-secret")
    assert "comp-secret" not in masked
    assert "***" in masked


# --- setup_logging ---


def test_setup_logging_returns_named_logger(tmp_path: Path, odin_logger: logging.Logger) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    assert logger is odin_logger
    assert logger.name == LOGGER_NAME


def test_setup_logging_handler_types(tmp_path: Path, odin_logger: logging.Logger) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    assert len(logger.handlers) == 2
    assert sum(isinstance(h, RotatingFileHandler) for h in logger.handlers) == 1
    assert sum(type(h) is logging.StreamHandler for h in logger.handlers) == 1


def test_setup_logging_rotation_defaults(tmp_path: Path, odin_logger: logging.Logger) -> None:
    config = _load_fixture_config(tmp_path)
    handler = _file_handler(setup_logging(config))
    assert handler.maxBytes == DEFAULT_MAX_BYTES == 5 * 1024 * 1024
    assert handler.backupCount == DEFAULT_BACKUP_COUNT == 5
    assert handler.encoding == "utf-8"


def test_setup_logging_format_includes_timestamp_level_and_name() -> None:
    assert "%(asctime)s" in LOG_FORMAT
    assert "%(levelname)" in LOG_FORMAT
    assert "%(name)s" in LOG_FORMAT
    assert "%(message)s" in LOG_FORMAT


def test_setup_logging_creates_default_log_dir(tmp_path: Path, odin_logger: logging.Logger) -> None:
    work_dir = tmp_path / "work"
    config = _load_fixture_config(tmp_path, work_dir=work_dir)
    logger = setup_logging(config)
    logger.info("creando directorio")
    log_path = work_dir / "logs" / LOG_FILENAME
    assert log_path.is_file()


def test_setup_logging_uses_explicit_log_dir(tmp_path: Path, odin_logger: logging.Logger) -> None:
    explicit = tmp_path / "logs-explicitos"
    config = _load_fixture_config(tmp_path, log_dir=explicit)
    logger = setup_logging(config)
    logger.info("hola log dir explícito")
    assert (explicit / LOG_FILENAME).is_file()
    assert not (config.local.work_dir / "logs").exists()


def test_setup_logging_level_from_config(tmp_path: Path, odin_logger: logging.Logger) -> None:
    config = _load_fixture_config(tmp_path, log_level="DEBUG")
    logger = setup_logging(config)
    assert logger.level == logging.DEBUG
    assert all(handler.level == logging.DEBUG for handler in logger.handlers)


def test_setup_logging_level_filters_messages(
    tmp_path: Path,
    odin_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_fixture_config(tmp_path, log_level="ERROR")
    logger = setup_logging(config)
    logger.info("no debe aparecer")
    logger.error("sí debe aparecer")
    assert "no debe aparecer" not in capsys.readouterr().err
    file_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "no debe aparecer" not in file_text
    assert "sí debe aparecer" in file_text


def test_setup_logging_writes_message_to_file_with_timestamp(
    tmp_path: Path, odin_logger: logging.Logger
) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    logger.info("respaldo iniciado")
    content = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "respaldo iniciado" in content
    assert "INFO" in content
    assert LOGGER_NAME in content
    assert _TIMESTAMP_RE.search(content) is not None


def test_setup_logging_writes_message_to_console(
    tmp_path: Path,
    odin_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    logger.info("mensaje a consola")
    err = capsys.readouterr().err
    assert "mensaje a consola" in err
    assert "INFO" in err


def test_setup_logging_masks_interpolated_args_in_both_destinations(
    tmp_path: Path,
    odin_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    logger.info("conectando a %s con clave %s", "erp_principal", "masterkey")
    err = capsys.readouterr().err
    file_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    for output in (err, file_text):
        assert "masterkey" not in output
        assert "conectando a erp_principal con clave ***" in output


def test_setup_logging_masks_compression_password(
    tmp_path: Path,
    odin_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_fixture_config(tmp_path, compression_password="comp-secret")
    logger = setup_logging(config)
    logger.info("cifrando .7z con password %s", "comp-secret")
    err = capsys.readouterr().err
    file_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    for output in (err, file_text):
        assert "comp-secret" not in output
        assert "***" in output


def test_setup_logging_masks_pem_block_in_file(tmp_path: Path, odin_logger: logging.Logger) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nSECRETO-DE-CLAVE\n-----END OPENSSH PRIVATE KEY-----"
    logger.warning("llave leída: %s", pem)
    file_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "SECRETO-DE-CLAVE" not in file_text
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in file_text


def test_setup_logging_idempotent(
    tmp_path: Path,
    odin_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_fixture_config(tmp_path)
    setup_logging(config)
    setup_logging(config)
    assert len(odin_logger.handlers) == 2
    odin_logger.info("tras doble setup")
    err = capsys.readouterr().err
    assert err.count("tras doble setup") == 1
    file_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert file_text.count("tras doble setup") == 1


def test_setup_logging_reload_changes_level(tmp_path: Path, odin_logger: logging.Logger) -> None:
    setup_logging(_load_fixture_config(tmp_path, log_level="INFO"))
    logger = setup_logging(_load_fixture_config(tmp_path, log_level="ERROR"))
    assert logger.level == logging.ERROR
    assert len(logger.handlers) == 2


def test_masking_filter_masks_record_args() -> None:
    record = logging.LogRecord(
        name=LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="clave %s",
        args=("masterkey",),
        exc_info=None,
    )
    assert MaskingFilter(SecretMasker(["masterkey"])).filter(record) is True
    assert record.getMessage() == "clave ***"
    assert record.args is None


def test_setup_logging_no_log_files_outside_configured_dir(
    tmp_path: Path, odin_logger: logging.Logger
) -> None:
    config = _load_fixture_config(tmp_path)
    logger = setup_logging(config)
    logger.info("verificación de ubicación")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json", "work"]
    assert (config.local.resolved_log_dir / LOG_FILENAME).is_file()
