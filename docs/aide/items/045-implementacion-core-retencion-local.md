# Item 045: Implementación core de la retención local (`src/odin/retention.py`)

## Description

Implementar la limpieza opcional de respaldos locales (F8) según `local.retention_days`: eliminar `.fbk` y `.fbk.7z` de `work_dir` con antigüedad mayor a N días (por `mtime`), **solo** archivos gestionados por ODIN — nombre que cumpla la convención `<nombre_bd>_<timestamp>.fbk` / `<nombre_bd>_<timestamp>.fbk.7z` de las Etapas 2-3 (`timestamp = %Y%m%d_%H%M%S`, `src/odin/backup.py:39`). `retention_days == 0` = deshabilitado. Seguridad: el path resuelto debe quedar dentro de `work_dir` (sin `..`), no seguir symlinks, solo archivos regulares, nunca tocar el directorio ni archivos ajenos (`config.json`, `odin.log`, etc.), y jamás los artefactos recién creados por la corrida actual (defensa extra: `mtime >=` inicio de la corrida queda excluido). Definir `RetentionResult` (examinados, eliminados, bytes liberados, errores por archivo, duración) y un ejecutor con aislamiento de fallos: un borrado fallido (p. ej. `PermissionError`/`OSError`) se registra y no interrumpe el resto. Idempotente.

## Acceptance Criteria

- [ ] `src/odin/retention.py` expone `RetentionResult`, `RetentionExecutor` (o equivalente), `is_managed_backup` y `__all__`.
- [ ] Solo se eliminan archivos regulares cuyo nombre cumple la convención ODIN y cuyo `mtime` es estrictamente anterior al cutoff (`ahora - retention_days días`); un archivo exactamente en el cutoff sobrevive.
- [ ] `retention_days == 0` (y valores negativos) no examinan ni borran nada (no-op idempotente).
- [ ] Quedan intactos: directorio `work_dir`, archivos ajenos (`config.json`, `odin.log`, `notas.fbk.txt`), subdirectorios, symlinks (a archivos o directorios) y todo archivo con `mtime >=` inicio de la corrida.
- [ ] Un `OSError`/`PermissionError` de borrado se registra en `RetentionResult.errors` y el resto continúa; la operación nunca propaga excepción operativa.
- [ ] Segunda ejecución sobre el mismo directorio: `deleted == 0`, sin errores (idempotencia).
- [ ] `RetentionResult` reporta examinados, eliminados, bytes liberados, errores por archivo (`path`, `message`) y duración.
- [ ] Tests unitarios en `tests/test_retention.py` con `tmp_path` cubriendo todos los casos anteriores.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Crear `src/odin/retention.py` con docstring de módulo (política F8, convención de nombres y garantías de seguridad) y `__all__`.
2. Definir `RetentionError` (frozen dataclass: `path`, `message`) y `RetentionResult` (frozen dataclass con slots: `examined`, `deleted`, `freed_bytes`, `errors`, `duration_seconds`, `enabled`).
3. Definir la detección de archivo gestionado: regex `^.+_\d{8}_\d{6}\.fbk(?:\.7z)?$` (mismo `%Y%m%d_%H%M%S` de `backup.py`) en una función pura `is_managed_backup(name) -> bool`.
4. Implementar `RetentionExecutor.run_retention(work_dir, retention_days, *, run_started_at=None) -> RetentionResult` con `time.perf_counter` para la duración y `now` inyectable (default `time.time`); default de `run_started_at` = instante de la llamada.
5. Seguridad por archivo: `entry.is_symlink()` → excluir; `entry.is_file()` → excluir si no es regular; `candidate.resolve().parent == root_resolved` (defensa anti-`..`); edad por `entry.stat().st_mtime`.
6. Aislar `OSError` por archivo en `errors` y loguear el resumen con `odin.log.logger` (sin secretos: solo nombres de archivo).
7. Escribir `tests/test_retention.py` con los casos del Testing Strategy.

## Testing Strategy

- `tests/test_retention.py` (`tmp_path`): frontera exacta del cutoff (cutoff-1 s borra, cutoff exacto y cutoff+1 s sobreviven), archivos ajenos intactos, subdirectorios y symlinks ignorados, `retention_days=0` no-op, error de borrado aislado (`monkeypatch` de `Path.unlink` o permiso de directorio), artefactos recientes protegidos por `mtime >= run_started_at`, idempotencia y `freed_bytes` correcto.
- Gates: `uv run pytest tests/test_retention.py`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Ninguna (módulo nuevo). Reutiliza el formato de timestamp de `src/odin/backup.py`.

## Decisions & Trade-offs

- **Convención validada por regex, no por config**: `is_managed_backup` acepta `^.+_\d{8}_\d{6}\.fbk(?:\.7z)?$` (mismo `%Y%m%d_%H%M%S` de `backup.py`). No se cruza contra `config.databases`: la retención debe limpiar también artefactos de bases retiradas de la config, que de otro modo quedarían huérfanos para siempre.
- **Dos relojes separados**: el cutoff es `now - retention_days * 86400` y la protección de la corrida actual compara contra `run_started_at` (default `now`). Si se usara un solo instante, la defensa anti-reloj-desfasado quedaría subsumida por el cutoff y no protegería nada.
- **Frontera estricta**: se borra solo con `mtime < cutoff` ("más de N días"); un archivo exactamente en el cutoff sobrevive. Decisión conservadora: ante la duda, no borrar.
- **`examined` cuenta candidatos gestionados, no entradas del directorio**: incluye nombres gestionados que luego se saltean por ser symlink/directorio/recientes; es la métrica útil para saber si la política está viendo los artefactos correctos.
- **`work_dir` ausente = no-op sin error**: no hay nada que limpiar (y el respaldo lo autocrea); solo un `iterdir` fallido (permisos) se registra como error.
- **Contención defensiva**: además de no seguir symlinks y exigir archivo regular, se verifica `entry.resolve().parent == work_dir.resolve()`; con nombres sin separadores es redundante, pero blinda ante cambios futuros en la iteración.
- **`RetentionResult.enabled`**: permite a la CLI distinguir "deshabilitada por config" de "habilitada sin nada que borrar" sin volver a consultar la config.

**Evidencia:** `uv run pytest tests/test_retention.py -q` → 25 passed (convención de nombres aceptados/rechazados, frontera estricta del cutoff, protección por `run_started_at`, `retention_days=0` y negativo no-op, `work_dir` ausente, subdirectorios/symlinks ignorados, error de borrado aislado, idempotencia, lookalikes intactos); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (13 source files).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
