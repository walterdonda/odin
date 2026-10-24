"""Tests unitarios de la compresión 7z (Items 020-023 y 027).

Comprimen archivos reales en directorios temporales y verifican el artefacto
con ``py7zr`` (ida y vuelta byte a byte), sin depender de un binario 7-Zip.
"""

from __future__ import annotations

import logging
import lzma
import os
from pathlib import Path
from unittest.mock import patch

import py7zr
import pytest

from odin.backup import BackupResult
from odin.compress import (
    DEFAULT_COMPRESSION_LEVEL,
    MAX_COMPRESSION_LEVEL,
    MIN_COMPRESSION_LEVEL,
    CompressionExecutor,
    archive_path_for,
    compress_backup,
)

PAYLOAD = (b"ODIN backup payload " * 4096) + bytes(range(256))
PASSWORD = "clave-de-prueba"
# py7zr cifra con un IV aleatorio por archivo, así que la basura que produce
# una clave incorrecta varía: el flujo LZMA2 puede ser inválido
# (``lzma.LZMAError``) o terminar antes de tiempo y recibir más datos
# (``EOFError``). ``ArchiveError`` cubre además un CRC que no cuadre.
WRONG_PASSWORD_ERRORS = (lzma.LZMAError, EOFError, py7zr.exceptions.ArchiveError)
# IV fijos que reproducen ambos fallos de forma determinista: con IV aleatorio
# el caso es inestable e incluso puede dejar al extractor de py7zr en un bucle
# sin progreso.
WRONG_PASSWORD_IVS = (
    pytest.param(b"\x00" * 16, id="lzma-error"),
    pytest.param(b"\xff" * 16, id="eof-error"),
)


def _extract(archive: Path, destination: Path, password: str | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(archive, "r", password=password) as sevenzip:
        sevenzip.extractall(path=destination)


def _round_trip(archive: Path, destination: Path, password: str | None = None) -> bytes:
    """Extrae el archivo único del ``.7z`` y devuelve sus bytes."""
    _extract(archive, destination, password)
    files = [path for path in destination.rglob("*") if path.is_file()]
    assert len(files) == 1
    return files[0].read_bytes()


@pytest.fixture()
def source_file(tmp_path: Path) -> Path:
    source = tmp_path / "erp_20260911_020000.fbk"
    source.write_bytes(PAYLOAD)
    return source


# --- compresión exitosa ---


def test_compress_creates_archive_with_default_name(source_file: Path, tmp_path: Path) -> None:
    result = compress_backup("erp_principal", source_file)

    assert result.success
    assert result.archive_path == tmp_path / "erp_20260911_020000.fbk.7z"
    assert result.archive_path.is_file()
    assert result.error_message is None


def test_result_reports_sizes_ratio_and_duration(source_file: Path) -> None:
    result = compress_backup("erp_principal", source_file)

    assert result.source_path == source_file
    assert result.original_size_bytes == source_file.stat().st_size
    assert result.archive_path is not None
    assert result.compressed_size_bytes == result.archive_path.stat().st_size
    assert result.compression_ratio == pytest.approx(
        result.compressed_size_bytes / result.original_size_bytes
    )
    assert result.duration_seconds > 0
    assert result.database_name == "erp_principal"


def test_round_trip_is_byte_identical(source_file: Path, tmp_path: Path) -> None:
    result = compress_backup("erp_principal", source_file)

    assert result.archive_path is not None
    assert _round_trip(result.archive_path, tmp_path / "extraido") == PAYLOAD


def test_explicit_archive_path(source_file: Path, tmp_path: Path) -> None:
    target = tmp_path / "destino" / "copia.fbk.7z"
    target.parent.mkdir()

    result = compress_backup("erp_principal", source_file, target)

    assert result.success
    assert result.archive_path == target
    assert target.is_file()


def test_archive_path_for_convention() -> None:
    assert archive_path_for("x.fbk") == Path("x.fbk.7z")
    assert archive_path_for(Path("/tmp/a.fbk")) == Path("/tmp/a.fbk.7z")


# --- nivel de compresión (Item 022) ---


def test_level_constants_document_the_range() -> None:
    assert DEFAULT_COMPRESSION_LEVEL == 7
    assert MIN_COMPRESSION_LEVEL == 0
    assert MAX_COMPRESSION_LEVEL == 9


def test_level_zero_stores_without_compression(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    result = compress_backup("erp_principal", source, level=0)

    assert result.success
    assert result.compressed_size_bytes is not None
    # modo store: el contenedor 7z pesa más que el original (cabecera + CRC)
    assert result.compressed_size_bytes > result.original_size_bytes
    assert result.archive_path is not None
    assert _round_trip(result.archive_path, tmp_path / "extraido") == PAYLOAD


def test_level_effect_is_measurable(tmp_path: Path) -> None:
    block = os.urandom(1_500_000)
    source = tmp_path / "grande.fbk"
    source.write_bytes(block * 3)

    low = compress_backup("erp_principal", source, tmp_path / "nivel1.7z", level=1)
    high = compress_backup("erp_principal", source, tmp_path / "nivel9.7z", level=9)

    assert low.success and high.success
    assert low.compressed_size_bytes is not None
    assert high.compressed_size_bytes is not None
    # el preset 1 (diccionario 1 MiB) no alcanza la redundancia de largo rango
    assert high.compressed_size_bytes < low.compressed_size_bytes


@pytest.mark.parametrize("level", [-1, 10])
def test_invalid_level_is_reported(tmp_path: Path, level: int) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    result = compress_backup("erp_principal", source, level=level)

    assert not result.success
    assert result.error_message is not None
    assert "nivel de compresión inválido" in result.error_message
    assert not (tmp_path / "origen.fbk.7z").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_effective_level_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    with caplog.at_level(logging.INFO, logger="odin.compress"):
        result = compress_backup("erp_principal", source, level=9)

    assert result.success
    assert "nivel 9" in caplog.text


# --- cifrado AES-256 opcional (Item 023) ---


def test_unencrypted_archive_reports_not_encrypted(source_file: Path) -> None:
    result = compress_backup("erp_principal", source_file)

    assert result.success
    assert result.encrypted is False


def test_encrypted_archive_round_trip(source_file: Path, tmp_path: Path) -> None:
    result = compress_backup("erp_principal", source_file, password=PASSWORD)

    assert result.success
    assert result.encrypted is True
    assert result.archive_path is not None
    assert _round_trip(result.archive_path, tmp_path / "extraido", PASSWORD) == PAYLOAD


def test_encrypted_archive_requires_password(source_file: Path, tmp_path: Path) -> None:
    result = compress_backup("erp_principal", source_file, password=PASSWORD)
    assert result.archive_path is not None

    with pytest.raises(py7zr.PasswordRequired):
        _extract(result.archive_path, tmp_path / "sin_clave")


@pytest.mark.parametrize("iv", WRONG_PASSWORD_IVS)
def test_encrypted_archive_wrong_password_fails(
    source_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, iv: bytes
) -> None:
    # Se fija el IV para que el fallo no dependa de bytes aleatorios: uno de
    # los casos reproduce el ``EOFError`` observado en CI y el otro el
    # ``lzma.LZMAError`` habitual.
    monkeypatch.setattr("py7zr.compressor.get_random_bytes", lambda size, iv=iv: iv)

    result = compress_backup("erp_principal", source_file, password=PASSWORD)
    assert result.archive_path is not None
    destination = tmp_path / "clave_incorrecta"

    with pytest.raises(WRONG_PASSWORD_ERRORS):
        _extract(result.archive_path, destination, "otra-clave")

    # La extracción fallida puede dejar un archivo parcial, pero nunca el
    # contenido original.
    assert not any(
        path.is_file() and path.read_bytes() == PAYLOAD for path in destination.rglob("*")
    )


# --- logging y enmascarado de secretos (Item 027) ---


def test_start_log_reports_level_and_encryption(
    source_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="odin.compress"):
        result = compress_backup("erp_principal", source_file, level=5, password=PASSWORD)

    assert result.success
    assert "nivel 5" in caplog.text
    assert "cifrado: sí" in caplog.text


def test_success_log_reports_sizes_ratio_and_duration(
    source_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="odin.compress"):
        result = compress_backup("erp_principal", source_file)

    assert result.success
    assert result.compressed_size_bytes is not None
    assert "Compresión exitosa" in caplog.text
    assert str(result.compressed_size_bytes) in caplog.text
    assert "del original" in caplog.text


def test_password_never_appears_in_logs(
    source_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="odin.compress"):
        result = compress_backup("erp_principal", source_file, password=PASSWORD)

    assert result.success
    assert PASSWORD not in caplog.text


def test_password_never_appears_in_failure_result_and_logs(
    source_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="odin.compress"),
        patch("odin.compress.py7zr.SevenZipFile", side_effect=OSError("disco lleno")),
    ):
        result = compress_backup("erp_principal", source_file, password=PASSWORD)

    assert not result.success
    assert result.error_message is not None
    assert PASSWORD not in result.error_message
    assert PASSWORD not in caplog.text


# --- errores operativos: se reportan, no se propagan ---


def test_missing_source_reports_error(tmp_path: Path) -> None:
    missing = tmp_path / "no_existe.fbk"

    result = compress_backup("erp_principal", missing)

    assert not result.success
    assert result.archive_path is None
    assert result.error_message is not None
    assert "no existe" in result.error_message
    assert not (tmp_path / "no_existe.fbk.7z").exists()


def test_empty_source_reports_error(tmp_path: Path) -> None:
    empty = tmp_path / "vacio.fbk"
    empty.touch()

    result = compress_backup("erp_principal", empty)

    assert not result.success
    assert result.error_message is not None
    assert "vacío" in result.error_message
    assert not (tmp_path / "vacio.fbk.7z").exists()


def test_py7zr_failure_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    with patch(
        "odin.compress.py7zr.SevenZipFile",
        side_effect=py7zr.exceptions.ArchiveError("fallo de py7zr"),
    ):
        result = compress_backup("erp_principal", source)

    assert not result.success
    assert result.error_message is not None
    assert "no se pudo comprimir" in result.error_message


# --- escritura atómica y destino existente (Item 021) ---


class _PartialThenFailArchive:
    """Doble de ``SevenZipFile``: escribe un temporal parcial y falla al salir."""

    def __init__(self, path: Path, mode: str = "w", **kwargs: object) -> None:
        self._path = Path(path)

    def __enter__(self) -> _PartialThenFailArchive:
        self._path.write_bytes(b"contenido parcial")
        return self

    def __exit__(self, *exc_info: object) -> None:
        raise OSError("No space left on device")

    def write(self, source: Path, arcname: str | None = None) -> None:
        """No-op: el contenido parcial ya se escribió en ``__enter__``."""


class _EmptyArchive:
    """Doble de ``SevenZipFile``: simula que ``py7zr`` no escribió nada."""

    def __init__(self, path: Path, mode: str = "w", **kwargs: object) -> None:
        pass

    def __enter__(self) -> _EmptyArchive:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def write(self, source: Path, arcname: str | None = None) -> None:
        """No-op."""


def test_failure_mid_compression_leaves_no_residue(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    with patch("odin.compress.py7zr.SevenZipFile", _PartialThenFailArchive):
        result = compress_backup("erp_principal", source)

    assert not result.success
    assert result.error_message is not None
    assert "no se pudo comprimir" in result.error_message
    assert not (tmp_path / "origen.fbk.7z").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_empty_archive_is_reported_and_temporary_removed(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)

    with patch("odin.compress.py7zr.SevenZipFile", _EmptyArchive):
        result = compress_backup("erp_principal", source)

    assert not result.success
    assert result.error_message is not None
    assert "vacío" in result.error_message
    assert not (tmp_path / "origen.fbk.7z").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_existing_archive_is_preserved_on_failure(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)
    target = tmp_path / "origen.fbk.7z"
    target.write_bytes(b"copia anterior intacta")

    with patch("odin.compress.py7zr.SevenZipFile", _PartialThenFailArchive):
        result = compress_backup("erp_principal", source)

    assert not result.success
    assert target.read_bytes() == b"copia anterior intacta"
    assert list(tmp_path.glob("*.tmp")) == []


def test_existing_archive_is_replaced_on_success(tmp_path: Path) -> None:
    source = tmp_path / "origen.fbk"
    source.write_bytes(PAYLOAD)
    target = tmp_path / "origen.fbk.7z"
    target.write_bytes(b"copia anterior")

    result = compress_backup("erp_principal", source)

    assert result.success
    assert target.read_bytes() != b"copia anterior"
    assert _round_trip(target, tmp_path / "extraido") == PAYLOAD
    assert list(tmp_path.glob("*.tmp")) == []


def test_missing_destination_directory_reports_error(source_file: Path, tmp_path: Path) -> None:
    target = tmp_path / "no" / "existe.fbk.7z"

    result = compress_backup("erp_principal", source_file, target)

    assert not result.success
    assert result.error_message is not None
    assert "temporal" in result.error_message


def test_no_temporary_files_after_success(source_file: Path, tmp_path: Path) -> None:
    result = compress_backup("erp_principal", source_file)

    assert result.success
    assert list(tmp_path.glob("*.tmp")) == []


# --- lote de compresión (Item 024) ---


def _successful_backup(tmp_path: Path, name: str = "erp_principal") -> BackupResult:
    source = tmp_path / f"{name}.fbk"
    source.write_bytes(PAYLOAD)
    return BackupResult(
        success=True,
        database_name=name,
        backup_path=source,
        file_size_bytes=len(PAYLOAD),
        duration_seconds=0.1,
    )


def _failed_backup(name: str = "erp_secundaria") -> BackupResult:
    return BackupResult(
        success=False,
        database_name=name,
        duration_seconds=0.1,
        error_message="gbak falló",
    )


def test_batch_compresses_only_successful_backups(tmp_path: Path) -> None:
    batch = CompressionExecutor().run_batch_compression(
        [_successful_backup(tmp_path, "db1"), _failed_backup("db2")]
    )

    assert batch.success
    assert [result.database_name for result in batch.results] == ["db1"]
    assert batch.results[0].success
    assert batch.results[0].archive_path == tmp_path / "db1.fbk.7z"
    assert (tmp_path / "db1.fbk.7z").is_file()
    assert batch.total_duration_seconds > 0


def test_batch_isolates_a_compression_failure(tmp_path: Path) -> None:
    missing = BackupResult(
        success=True,
        database_name="db2",
        backup_path=tmp_path / "no_existe.fbk",
        file_size_bytes=1,
        duration_seconds=0.1,
    )

    batch = CompressionExecutor().run_batch_compression(
        [_successful_backup(tmp_path, "db1"), missing]
    )

    assert not batch.success
    assert [result.success for result in batch.results] == [True, False]
    assert batch.results[0].archive_path is not None
    assert batch.results[1].error_message is not None
    assert "no existe" in batch.results[1].error_message
    assert (tmp_path / "db1.fbk.7z").is_file()


def test_batch_without_successful_backups_does_not_compress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    def spy(*args: object, **kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr("odin.compress.compress_backup", spy)

    batch = CompressionExecutor().run_batch_compression([_failed_backup("db1")])

    assert batch.results == []
    assert not batch.success
    assert calls == []


def test_empty_batch_has_no_results() -> None:
    batch = CompressionExecutor().run_batch_compression([])

    assert batch.results == []
    assert not batch.success


def test_batch_forwards_level_and_password(tmp_path: Path) -> None:
    batch = CompressionExecutor(level=9, password=PASSWORD).run_batch_compression(
        [_successful_backup(tmp_path)]
    )

    assert batch.success
    result = batch.results[0]
    assert result.encrypted is True
    assert result.archive_path is not None
    with pytest.raises(py7zr.PasswordRequired):
        _extract(result.archive_path, tmp_path / "sin_clave")
