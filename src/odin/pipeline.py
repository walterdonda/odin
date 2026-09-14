"""Pipeline de ``odin run``: respaldo → compresión → transferencia (Item 035).

``run_pipeline`` orquesta las tres fases acumuladas por base:

1. **Respaldo** (Etapa 2): ``BackupExecutor.run_batch_backup`` sobre todas las
   bases de la configuración.
2. **Compresión** (Etapa 3): ``CompressionExecutor.run_batch_compression``
   sobre los respaldos exitosos.
3. **Transferencia** (Etapa 4): para cada base con respaldo + compresión
   exitosos, ``TransferExecutor.run_batch_transfer`` envía el ``.fbk.7z`` a
   todos los servidores configurados, aislando los fallos por destino.

El éxito global depende de la culminación exitosa de todas las fases para
cada base: una base con transferencia fallida queda marcada como fallida en
el ``BatchBackupResult`` final (``transfer_error_message``) conservando los
datos de respaldo/compresión. Sin servidores configurados la fase de
transferencia se considera satisfecha (nada que transferir).

El módulo no propaga excepciones operativas: cada fase ya encapsula sus
errores en sus propios resultados (patrón de aislamiento de fallos de las
Etapas 2-4). Los ejecutores son inyectables para tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from odin.backup import BackupExecutor, BackupResult, BatchBackupResult
from odin.compress import BatchCompressionResult, CompressionExecutor
from odin.config import Config
from odin.transfer import (
    BatchTransferResult,
    TransferExecutor,
    TransferResult,
    aggregate_transfer_results,
)

__all__ = ["PipelineResult", "run_pipeline"]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Resultado del pipeline completo de ``odin run``.

    ``backup`` es el lote fusionado de respaldo + compresión cuyo ``success``
    por base **ya incluye la transferencia** (Item 035). ``transfers`` agrupa
    los ``BatchTransferResult`` por base transferida (bases con respaldo +
    compresión exitosos, en el orden de la configuración de servidores);
    las bases que no llegaron a transferirse no aparecen en el mapping.
    """

    backup: BatchBackupResult
    transfers: Mapping[str, BatchTransferResult]


def _merge_compression_results(
    batch: BatchBackupResult, compressed: BatchCompressionResult
) -> BatchBackupResult:
    """Cruza respaldo y compresión por base (Item 025, movido desde ``odin.cli``).

    Una base cuenta como exitosa solo si el respaldo y la compresión
    culminaron bien: un fallo de compresión marca la base como fallida con
    ``compression_error_message`` y conserva los datos del respaldo (ruta,
    tamaño y duración) para el resumen.
    """
    by_name = {result.database_name: result for result in compressed.results}
    merged: list[BackupResult] = []
    for backup in batch.results:
        compression = by_name.get(backup.database_name)
        if not backup.success or backup.backup_path is None:
            merged.append(backup)
        elif compression is None:
            merged.append(
                replace(
                    backup,
                    success=False,
                    compression_error_message="no se intentó la compresión del respaldo",
                )
            )
        elif not compression.success:
            merged.append(
                replace(
                    backup,
                    success=False,
                    compression_error_message=compression.error_message,
                )
            )
        else:
            merged.append(
                replace(
                    backup,
                    archive_path=compression.archive_path,
                    compressed_size_bytes=compression.compressed_size_bytes,
                    compression_duration_seconds=compression.duration_seconds,
                )
            )
    return replace(
        batch,
        results=merged,
        success=bool(merged) and all(result.success for result in merged),
        total_duration_seconds=batch.total_duration_seconds
        + compressed.total_duration_seconds,
    )


def _transfer_error_detail(results: Sequence[TransferResult]) -> str:
    """Resume los destinos fallidos de un lote de transferencia por base."""
    failed = [result for result in results if not result.success]
    return "; ".join(
        f"{result.server_name}: {result.error_message or 'fallo sin detalle'}"
        for result in failed
    )


def run_pipeline(
    config: Config,
    *,
    backup: BackupExecutor | None = None,
    compression: CompressionExecutor | None = None,
    transfer: TransferExecutor | None = None,
) -> PipelineResult:
    """Ejecuta el pipeline completo de ``odin run`` y devuelve el resultado.

    Los ejecutores se construyen desde ``config`` (``local.gbak_timeout_sec``
    para respaldo; ``compression.level``/``password`` para compresión) y son
    inyectables para tests. Cada fase aísla sus fallos; el éxito global exige
    que todas las fases culminen bien para cada base.
    """
    backup_executor = backup or BackupExecutor(timeout=config.local.gbak_timeout_sec)
    compression_executor = compression or CompressionExecutor(
        level=config.compression.level,
        password=config.compression.password,
    )
    transfer_executor = transfer or TransferExecutor()

    batch = backup_executor.run_batch_backup(config.databases, config.local.work_dir)
    compressed = compression_executor.run_batch_compression(batch.results)
    merged = _merge_compression_results(batch, compressed)

    transfers: dict[str, BatchTransferResult] = {}
    final_results: list[BackupResult] = []
    for result in merged.results:
        if not result.success or result.archive_path is None:
            final_results.append(result)
            continue
        if not config.servers:
            final_results.append(result)
            continue
        transfer_results = transfer_executor.run_batch_transfer(
            config.servers, result.archive_path
        )
        batch_transfer = aggregate_transfer_results(transfer_results)
        transfers[result.database_name] = batch_transfer
        if batch_transfer.success:
            final_results.append(result)
        else:
            final_results.append(
                replace(
                    result,
                    success=False,
                    transfer_error_message=_transfer_error_detail(batch_transfer.results),
                )
            )

    final_batch = replace(
        merged,
        results=final_results,
        success=bool(final_results) and all(result.success for result in final_results),
    )
    return PipelineResult(backup=final_batch, transfers=transfers)
