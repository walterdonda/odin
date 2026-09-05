# Item 003: Normalización OS-agnóstica de rutas

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 003. Etapa 1 del roadmap.

---

## Descripción

Implementar `src/odin/paths.py`: normalización de rutas de configuración **OS-agnóstica** usando solo stdlib (`pathlib`, `re`, `os`). El módulo acepta separadores `/` y `\` indistintamente, expande `~` (y `~usuario`) sin importar el separador usado, y resuelve rutas relativas contra el directorio del archivo JSON de configuración. El Item 002 dejó resueltas las rutas relativas con `pathlib` básico; este item completa la normalización anunciada en su criterio de aceptación 6.

Integrar la normalización en `src/odin/config.py` para los campos de rutas locales: `local.work_dir`, `local.log_dir`, `databases[].gbak_path` y `servers[].auth.private_key`. `servers[].remote_path` queda excluido (semántica remota POSIX; se trata en la Etapa 4).

## Criterios de Aceptación

1. `normalize_path(raw, base_dir=...)` devuelve un `Path` con: `~`/`~usuario` expandidos, separadores `/` y `\` normalizados (ambos aceptados en cualquier SO), y rutas relativas resueltas contra `base_dir`.
2. Una ruta absoluta con sabor Windows (letra de unidad `D:\...`, `C:/...` o UNC `\\srv\share`) **no** se resuelve contra `base_dir` aunque se parsee en Linux, y viceversa con rutas POSIX en Windows.
3. La expansión de `~` funciona con ambos separadores (`~/.ssh/id` y `~\.ssh\id`) y sin depender de `PurePath.expanduser` (no existe en Python 3.14 para rutas puras).
4. Integración en `config.py`: `work_dir`, `log_dir`, `gbak_path` y `private_key` pasan por `normalize_path` contra el directorio del JSON; `base_dir` se ancla a ruta absoluta (lexical, sin resolver symlinks) para que un `--config` relativo no produzca rutas relativas.
5. Tests unitarios (`tests/test_paths.py`) con rutas POSIX, Windows (unidad, UNC, mixtas), `~`, y relativas, en ambas direcciones de normalización; tests de integración vía `load_config` (rutas Windows no reciben prefijo del JSON, `~` con `\` se expande, `--config` relativo ancla contra CWD).
6. Sin dependencias de terceros; `uv run pytest -q` verde; `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy` limpios.
7. Los tests existentes del Item 002 siguen pasando sin cambios de comportamiento observable (resolución de relativas contra el directorio del JSON).

## Pasos de Implementación

1. **`src/odin/paths.py`** (solo stdlib):
   - `is_windows_flavor(raw: str) -> bool`: detecta sabor Windows (contiene `\`, o prefijo de letra de unidad `[A-Za-z]:`). El prefijo UNC `//` no se trata como Windows porque su forma canónica coincide con la POSIX.
   - `expand_user(raw: str) -> str`: expande el segmento inicial `~`/`~usuario` aceptando `/` y `\` como separadores; `~` → `Path.home()`; `~usuario` delega en `os.path.expanduser` (ntpath no resuelve `~usuario`: documentado).
   - `normalize_path(raw: str, *, base_dir: Path | str | None = None) -> Path`: strip → `expand_user` → parseo según sabor (`PureWindowsPath` / `PurePosixPath`) → absolutitud según el sabor (no el SO actual) → forma canónica vía `as_posix()` → si es relativa y hay `base_dir`, `Path(base_dir) / canónica`. Cadena vacía → `ValueError`.
   - Documentar: `..` no se colapsa léxicamente (pathlib 3.14 lo preserva); un `\` literal en un nombre de archivo Linux se interpreta como separador (trade-off aceptado por el contrato OS-agnóstico).
2. **Integración en `config.py`:** reemplazar los helpers locales `_is_absolute`/`_resolve_path` por `odin.paths.normalize_path` en `_parse_local` (`work_dir`, `log_dir`), `_parse_database` (`gbak_path`) y `_parse_auth` (`private_key`); en `load_config`, `base_dir = config_path.parent.absolute()`.
3. **Tests (`tests/test_paths.py`):** casos POSIX, Windows unidad/UNC/mixtas/drive-relative, `~` con ambos separadores, `~usuario`, relativas con y sin `./`, strip de espacios, vacío → `ValueError`, idempotencia, unitarios de `is_windows_flavor`/`expand_user`.
4. **Tests de integración (extensión de `tests/test_config.py`):** `work_dir` Windows en Linux sin prefijo del JSON; `private_key` `~\...` expandido; `gbak_path` relativo con `\`; `load_config` con ruta relativa (vía `monkeypatch.chdir`) anclada contra CWD.

## Estrategia de Testing

- Unit tests puros (sin servicios externos; `tmp_path`/`monkeypatch` de pytest donde haga falta).
- Asertos portables vía `as_posix()` para que la suite pase en Linux y Windows.
- Gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Dependencias

- **De items anteriores:** Item 002 (`config.py`, helpers de resolución básica) — completado ✅.
- **Bloquea a:** Items 004 (log_dir efectivo para el logger), 006 (validate de rutas existentes) y Etapas 2/4 (uso de `gbak_path`/`private_key` normalizados).

## Prerrequisitos de Testing

### Servicios Requeridos
- Ninguno: normalización de rutas es lógica pura.

### Configuración de Entorno
- Entorno del Item 001 operativo (`uv sync`). Sin variables de entorno ni secretos.

### Checklist de Validación Manual
- [x] **Tests pasan:** `uv run pytest -q` verde (73 tests: 33 de paths, 36 de config —incluye 4 de integración nueva—, 4 smoke).
- [x] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy` sin errores.
- [x] **Funcionalidad verificada:** ambas direcciones de normalización (POSIX y Windows) cubiertas por tests en el SO de desarrollo (Linux); `load_config` sobre ambas fixtures reales normaliza `work_dir` (`/var/backups/odin`, `D:\Backups\odin` → `D:/Backups/odin` sin prefijo del JSON) y expande `~/.ssh/id_ed25519` al home.

### Resultados Esperados
- Archivos nuevos: `src/odin/paths.py`, `tests/test_paths.py`.
- Archivo modificado: `src/odin/config.py` (integración; sin cambios de API pública).
- ≥ 20 tests nuevos pasando; suite del Item 002 intacta.
- Ninguna dependencia nueva en `pyproject.toml`.

## Decisions & Trade-offs

> Actualizado durante la implementación (2026-09-05).

1. **Absolutitud por *sabor*, no por SO:** `is_windows_flavor` (contiene `\` o prefijo `[A-Za-z]:`) elige el parser (`PureWindowsPath`/`PurePosixPath`) y la absolutitud se juzga con ese parser. Así `D:\Backups\odin` parseado en Linux no recibe el prefijo del directorio del JSON. Alternativa descartada: error de validación ante rutas de otro SO — prematuro; la verificación de existencia/creabilidad corresponde a `odin validate` (Item 006). Trade-off: un `work_dir` Windows en Linux queda como ruta literal (`D:/Backups/odin`) que solo fallará en validación/uso posterior.
2. **Forma canónica intermedia `as_posix()`:** la normalización convierte a string canónico con `/` y luego construye el `Path` del SO actual (en Windows `Path` acepta `/` y emite `\` nativo). Esto hace el núcleo testeable en ambas direcciones desde cualquier SO; los tests asertan con `as_posix()` para portabilidad.
3. **`expand_user` propio:** `PurePath.expanduser` no existe en Python 3.14 (verificado empíricamente) y el de `Path` concreto depende del sabor del SO. Implementación: segmento inicial hasta el primer `/` o `\`; `~` → `Path.home()`, `~usuario` delega en `os.path.expanduser`. En Windows ntpath no resuelve `~usuario` (sin base de usuarios): se conserva sin cambios, documentado y testeado con `skipif`.
4. **`base_dir` anclado con `.absolute()`:** lexical (sin resolver symlinks), para que un `--config` relativo fije las rutas contra CWD + directorio del JSON. `Config.config_path` se preserva como fue dada (contrato del Item 002).
5. **Alcance de la integración:** además de los tres campos del enunciado se normaliza `local.log_dir` (extensión del Item 002, ruta local con el mismo ciclo de vida que `work_dir`). Excluidos: `servers[].remote_path` (semántica remota SFTP, Etapa 4), `databases[].connection` (puede incluir prefijo `host:port`) y secciones sin rutas.
6. **`.` se elimina, `..` se preserva:** comportamiento lexical de pathlib 3.14 (verificado); no se usa `Path.resolve()` porque toca el filesystem y cambiaría semántica de rutas inexistentes. Documentado en el módulo y testeado.
7. **Cadena vacía → `ValueError`:** la validación de config rechaza vacías antes de llegar aquí; el helper se defiende con error claro para usos futuros (Etapa 2+).
8. **`\` literal en nombres Linux:** se interpreta como separador; se acepta como trade-off del contrato OS-agnóstico y se documenta en el docstring del módulo.

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md`: el entregable "Normalización OS-agnóstica de rutas..." de la Etapa 1 debe pasar de 📋 → 🚧 → ✅. Este paso es parte de `/speckit.aide.execute-item`.

## Próximo Paso

Al completar, iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.create-item` con el número **004** (logging con rotación y enmascarado de secretos), luego `/speckit.aide.execute-item`.
