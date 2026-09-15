"""Retención local (F8, Item 045): limpieza de respaldos gestionados por ODIN.

Política: cuando ``local.retention_days`` es mayor que cero, ``odin run``
elimina de ``work_dir`` los artefactos ``<nombre_bd>_<timestamp>.fbk`` y
``<nombre_bd>_<timestamp>.fbk.7z`` (timestamp ``%Y%m%d_%H%M%S``, la
convención de nombres de ``odin.backup``) cuya antigüedad supere N días según
``mtime``. Con ``retention_days == 0`` la limpieza queda deshabilitada.

Seguridad (solo se toca lo que es de ODIN):

- Solo archivos **regulares** cuyo nombre cumpla la convención; un
  subdirectorio, un symlink o un archivo ajeno (``config.json``,
  ``odin.log``, ``notas.fbk.txt``) nunca se examina ni se borra.
- El path resuelto debe quedar dentro de ``work_dir`` (defensa extra frente a
  ``..`` inesperados); no se siguen symlinks.
- Los artefactos recién creados por la corrida actual quedan excluidos aunque
  su ``mtime`` sea antiguo (relojes desfasados): ``mtime >= inicio de la
  corrida`` no se borra.
- La frontera del cutoff es estricta: un archivo exactamente en ``ahora - N
  días`` sobrevive ("más de N días" = estrictamente anterior).

Aislamiento de fallos: un borrado fallido (``PermissionError``/``OSError``)
se registra en ``RetentionResult.errors`` con su path y mensaje, y el resto
continúa. La operación es idempotente: una segunda pasada no encuentra nada
que borrar.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from odin.log import logger

__all__ = [
    "RetentionError",
    "RetentionExecutor",
    "RetentionResult",
    "is_managed_backup",
]

_MANAGED_BACKUP_RE = re.compile(r"^.+_\d{8}_\d{6}\.fbk(?:\.7z)?$")
_SECONDS_PER_DAY = 86400.0


def is_managed_backup(name: str) -> bool:
    """True si ``name`` cumple la convención de artefactos de ODIN.

    La convención la fija ``odin.backup``: ``<nombre_bd>_<timestamp>.fbk``
    (con ``timestamp = %Y%m%d_%H%M%S``) y su comprimido ``.fbk.7z``. Todo lo
    demás (config, logs, notas, directorios) es ajeno y no se toca.
    """
    return _MANAGED_BACKUP_RE.match(name) is not None


@dataclass(frozen=True, slots=True)
class RetentionError:
    """Fallo de borrado de un archivo concreto (aislado del resto)."""

    path: str
    message: str


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """Resultado de una pasada de retención.

    ``examined`` cuenta los artefactos gestionados encontrados (candidatos a
    limpieza); ``deleted`` y ``freed_bytes`` los que se eliminaron y el
    espacio liberado. ``enabled`` es ``False`` cuando la política está
    deshabilitada (``retention_days == 0``) y no se examinó nada.
    """

    examined: int = 0
    deleted: int = 0
    freed_bytes: int = 0
    errors: tuple[RetentionError, ...] = ()
    duration_seconds: float = 0.0
    enabled: bool = True


class RetentionExecutor:
    """Ejecuta la política de retención sobre ``work_dir``.

    ``now`` es inyectable para tests deterministas (default ``time.time``).
    """

    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now

    def run_retention(
        self,
        work_dir: str | Path,
        retention_days: int,
        *,
        run_started_at: float | None = None,
    ) -> RetentionResult:
        """Elimina los artefactos gestionados más antiguos que ``retention_days``.

        El cutoff se calcula contra el instante actual (``now``, inyectable);
        ``run_started_at`` protege además los artefactos de la corrida actual
        (``mtime >=`` ese instante), por defecto el mismo ``now``. Nunca
        propaga una excepción operativa: los fallos quedan en
        ``RetentionResult.errors``.
        """
        start = time.perf_counter()
        now = self._now()
        run_start = now if run_started_at is None else run_started_at
        if retention_days <= 0:
            return RetentionResult(
                duration_seconds=time.perf_counter() - start, enabled=False
            )

        root = Path(work_dir)
        if not root.is_dir():
            return RetentionResult(duration_seconds=time.perf_counter() - start)

        cutoff = now - retention_days * _SECONDS_PER_DAY
        root_resolved = root.resolve()
        examined = 0
        deleted = 0
        freed_bytes = 0
        errors: list[RetentionError] = []

        try:
            entries = sorted(root.iterdir(), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(RetentionError(path=str(root), message=str(exc)))
            return RetentionResult(
                errors=tuple(errors), duration_seconds=time.perf_counter() - start
            )

        for entry in entries:
            if not is_managed_backup(entry.name):
                continue
            examined += 1
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                stat = entry.stat()
                if stat.st_mtime >= run_start or stat.st_mtime >= cutoff:
                    continue
                if entry.resolve().parent != root_resolved:
                    continue
                size = stat.st_size
                entry.unlink()
            except OSError as exc:
                errors.append(RetentionError(path=str(entry), message=str(exc)))
                logger.warning("No se pudo eliminar '%s': %s", entry, exc)
                continue
            deleted += 1
            freed_bytes += size
            logger.info("Retención local: eliminado '%s' (%d bytes)", entry, size)

        result = RetentionResult(
            examined=examined,
            deleted=deleted,
            freed_bytes=freed_bytes,
            errors=tuple(errors),
            duration_seconds=time.perf_counter() - start,
        )
        logger.info(
            "Retención local: %d/%d archivo(s) gestionados eliminados, %d bytes liberados",
            deleted,
            examined,
            freed_bytes,
        )
        return result
