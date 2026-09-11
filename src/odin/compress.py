"""Compresión 7z de los respaldos con ``py7zr`` (Etapa 3, Items 020-023).

Responsabilidades:

- Comprimir un ``.fbk`` validado a ``.fbk.7z`` con el nivel configurado
  (``compression.level``, 0-9): ``0`` = sin compresión (modo "store") y
  ``1-9`` = ``FILTER_LZMA2`` con ``preset`` igual al nivel. El rango se valida
  también acá (defensa en profundidad sobre ``config.py``).
- Validar el artefacto resultante (existe, tamaño > 0 y legible) y reportar
  tamaño original/comprimido, ratio y duración.
- Reportar los errores operativos esperados (origen inexistente/vacío/no
  legible, fallo de ``py7zr``, permisos, disco lleno) en ``CompressionResult``
  con ``success=False``; no se propagan como excepción para que el lote de
  compresión (Item 024) aísle los fallos por base.
- Escritura atómica (Item 021): se comprime a un temporal único en el
  directorio destino y se publica con ``os.replace`` solo después de validar
  el artefacto. Ante cualquier fallo el temporal se elimina, de modo que no
  quedan ``.7z`` parciales huérfanos. Un destino preexistente se reemplaza
  recién cuando la nueva copia está completa: una compresión fallida nunca
  corrompe la copia anterior.
- Cifrado opcional (Item 023): con ``compression.password`` definido,
  ``py7zr`` aplica 7zAES (AES-256) al contenido. Decisión: **no** se cifra la
  cabecera (``header_encryption=False``); el cifrado de cabecera de py7zr
  1.1.3 falla con ``TypeError`` ilegible ante contraseña incorrecta, mientras
  que el cifrado solo de contenido falla de forma estable con
  ``lzma.LZMAError``. La contraseña nunca se registra ni viaja en mensajes.
  En py7zr 1.1.3 el filtro AES solo se inyecta automáticamente cuando
  ``filters`` es ``None``; como acá se pasan filtros explícitos de nivel, el
  filtro ``FILTER_CRYPTO_AES256_SHA256`` se agrega a mano tras el de
  compresión (el orden del pipeline 7z es comprimir y luego cifrar).

La ruta destino por defecto sigue la convención ``<origen>.7z`` (p. ej.
``erp_20260911_020000.fbk`` → ``erp_20260911_020000.fbk.7z``).
"""

from __future__ import annotations

import logging
import lzma
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import py7zr

logger = logging.getLogger(__name__)

ARCHIVE_SUFFIX = ".7z"
DEFAULT_COMPRESSION_LEVEL = 7
MIN_COMPRESSION_LEVEL = 0
MAX_COMPRESSION_LEVEL = 9


class CompressionError(Exception):
    """Error operativo de compresión (base de los errores de la Etapa 3)."""


@dataclass(frozen=True, slots=True)
class CompressionResult:
    """Resultado de comprimir un respaldo (éxito o fallo con causa).

    ``compression_ratio`` es la fracción del tamaño original que ocupa el
    comprimido (``compressed_size / original_size``; ``1.0`` = sin reducción,
    menor es mejor).
    """

    success: bool
    database_name: str
    source_path: Path
    archive_path: Path | None = None
    original_size_bytes: int | None = None
    compressed_size_bytes: int | None = None
    compression_ratio: float | None = None
    duration_seconds: float = 0.0
    encrypted: bool = False
    error_message: str | None = None


def archive_path_for(source_path: str | Path) -> Path:
    """Ruta canónica del comprimido: ``<origen>.7z`` (p. ej. ``x.fbk`` → ``x.fbk.7z``)."""
    source = Path(source_path)
    return source.with_name(source.name + ARCHIVE_SUFFIX)


def compress_backup(
    database_name: str,
    source_path: str | Path,
    archive_path: str | Path | None = None,
    *,
    level: int = DEFAULT_COMPRESSION_LEVEL,
    password: str | None = None,
) -> CompressionResult:
    """Comprime ``source_path`` en ``archive_path`` (default ``<origen>.7z``).

    Con ``password`` definido el contenido se cifra con 7zAES (AES-256);
    ``None`` (default) genera un ``.7z`` sin cifrar. No propaga errores
    operativos: origen inexistente/vacío/no legible, fallo de ``py7zr``,
    permisos o I/O se devuelven como ``CompressionResult`` con
    ``success=False`` y un mensaje claro.
    """
    start_time = time.perf_counter()
    source = Path(source_path)
    target = Path(archive_path) if archive_path is not None else archive_path_for(source)
    encrypted = password is not None

    try:
        original_size = _validate_source(source)
        filters = _filters_for_level(level)
        if encrypted:
            # py7zr 1.1.3 solo inyecta AES cuando ``filters is None``; con
            # filtros explícitos hay que agregarlo tras el de compresión.
            filters.append({"id": py7zr.FILTER_CRYPTO_AES256_SHA256})
    except CompressionError as exc:
        return _failure(database_name, source, start_time, str(exc), encrypted=encrypted)

    logger.info(
        "Comprimiendo '%s': %s → %s (nivel %d, cifrado: %s)",
        database_name,
        source,
        target,
        level,
        "sí" if encrypted else "no",
    )
    try:
        temporary_path = _create_temporary_path(target)
    except OSError as exc:
        return _failure(
            database_name,
            source,
            start_time,
            f"no se pudo preparar el temporal en {target.parent}: {exc}",
            encrypted=encrypted,
        )
    try:
        _write_archive(temporary_path, source, filters, password)
        compressed_size = _validate_archive(temporary_path, display_path=target)
        os.replace(temporary_path, target)
    except CompressionError as exc:
        temporary_path.unlink(missing_ok=True)
        return _failure(database_name, source, start_time, str(exc), encrypted=encrypted)
    except (OSError, py7zr.exceptions.ArchiveError, lzma.LZMAError) as exc:
        temporary_path.unlink(missing_ok=True)
        return _failure(
            database_name,
            source,
            start_time,
            f"no se pudo comprimir {source}: {exc}",
            encrypted=encrypted,
        )

    duration = time.perf_counter() - start_time
    ratio = compressed_size / original_size
    logger.info(
        "Compresión exitosa de '%s': %s (%d → %d bytes, %.1f %% del original, %.1f s)",
        database_name,
        target,
        original_size,
        compressed_size,
        ratio * 100,
        duration,
    )
    return CompressionResult(
        success=True,
        database_name=database_name,
        source_path=source,
        archive_path=target,
        original_size_bytes=original_size,
        compressed_size_bytes=compressed_size,
        compression_ratio=ratio,
        duration_seconds=duration,
        encrypted=encrypted,
    )


def _filters_for_level(level: int) -> list[dict[str, int]]:
    """Mapea ``compression.level`` (0-9) a los filtros de ``py7zr``.

    ``0`` = sin compresión (``FILTER_COPY``, modo "store" de 7-Zip);
    ``1-9`` = ``FILTER_LZMA2`` con ``preset`` igual al nivel (el preset
    controla el diccionario y el esfuerzo del algoritmo). Lanza
    ``CompressionError`` fuera de rango; la validación existe también en
    ``config.py`` (Item 002) como defensa en profundidad.
    """
    if not MIN_COMPRESSION_LEVEL <= level <= MAX_COMPRESSION_LEVEL:
        raise CompressionError(
            f"nivel de compresión inválido: {level}; se esperaba un entero "
            f"entre {MIN_COMPRESSION_LEVEL} y {MAX_COMPRESSION_LEVEL}"
        )
    if level == MIN_COMPRESSION_LEVEL:
        return [{"id": py7zr.FILTER_COPY}]
    return [{"id": py7zr.FILTER_LZMA2, "preset": level}]


def _write_archive(
    target: Path, source: Path, filters: list[dict[str, int]], password: str | None
) -> None:
    """Escribe el ``.7z`` en ``target`` (cifrado con 7zAES si hay ``password``).

    No se cifra la cabecera del archivo (ver docstring del módulo): el cifrado
    solo de contenido tiene un modo de fallo estable y legible ante
    contraseña incorrecta.
    """
    with py7zr.SevenZipFile(target, "w", filters=filters, password=password) as archive:
        archive.write(source, arcname=source.name)


def _create_temporary_path(target: Path) -> Path:
    """Crea un temporal único y cerrado en el directorio del destino.

    ``mkstemp`` devuelve un descriptor abierto; se cierra de inmediato para
    que ``py7zr`` pueda abrir la ruta también en Windows. El temporal vive en
    el mismo directorio que el destino para que ``os.replace`` sea atómico
    (mismo sistema de archivos).
    """
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    return Path(name)


def _validate_source(path: Path) -> int:
    """Valida el ``.fbk`` de origen (existe, no vacío y legible) y devuelve su tamaño."""
    if not path.exists():
        raise CompressionError(f"el archivo de origen no existe: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CompressionError(f"no se pudo leer el archivo de origen {path}: {exc}") from exc
    if size <= 0:
        raise CompressionError(f"el archivo de origen está vacío: {path}")
    if not os.access(path, os.R_OK):
        raise CompressionError(f"el archivo de origen no es legible: {path}")
    return size


def _validate_archive(path: Path, display_path: Path | None = None) -> int:
    """Valida el ``.7z`` generado (existe, no vacío y legible) y devuelve su tamaño.

    ``display_path`` permite reportar la ruta final aunque la validación corra
    sobre el temporal interno (Item 021).
    """
    shown = display_path if display_path is not None else path
    if not path.exists():
        raise CompressionError(f"py7zr no generó el archivo comprimido: {shown}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CompressionError(f"no se pudo leer el archivo comprimido {shown}: {exc}") from exc
    if size <= 0:
        raise CompressionError(f"el archivo comprimido está vacío: {shown}")
    if not os.access(path, os.R_OK):
        raise CompressionError(f"el archivo comprimido no es legible: {shown}")
    return size


def _failure(
    database_name: str,
    source: Path,
    start_time: float,
    message: str,
    *,
    encrypted: bool = False,
) -> CompressionResult:
    """Construye y registra un ``CompressionResult`` fallido."""
    duration = time.perf_counter() - start_time
    logger.error("Compresión fallida de '%s': %s", database_name, message)
    return CompressionResult(
        success=False,
        database_name=database_name,
        source_path=source,
        duration_seconds=duration,
        encrypted=encrypted,
        error_message=message,
    )
