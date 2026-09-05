# Item 001: Esqueleto del paquete y pyproject con dependencias

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 001. Etapa 1 del roadmap.

---

## Descripción

Crear la estructura base del proyecto ODIN siguiendo las mejores prácticas de Python moderno: **layout `src/`**, metadatos completos en `pyproject.toml` (PEP 621) con backend de build **hatchling**, dependencias de runtime y de desarrollo declaradas, herramienta de lint/format (**ruff**) y tipado (**mypy**) configurados, script de consola `odin` registrado, y una suite **pytest** mínima de humo. Al finalizar, `uv sync` resuelve e instala todo el entorno (con `uv.lock` versionado), el paquete es importable y el comando `odin` responde.

Este item es fundacional: todas las etapas posteriores asumen esta estructura. No incluye lógica de negocio (config, CLI real, etc. — eso lo cubren los items 002–006); el módulo `cli.py` aquí es un **stub mínimo** (`--version`/`--help`) solo para que el console script resuelva.

## Criterios de Aceptación

1. `uv sync` completa sin errores en Linux (y genera/actualiza `uv.lock` resolviendo también el marker de Windows).
2. `uv run python -c "import odin; print(odin.__version__)"` imprime `0.1.0`.
3. `uv run odin --version` y `uv run odin --help` funcionan con exit code 0.
4. `uv run pytest -q` pasa (tests de humo: import del paquete, versión, invocación del stub de CLI).
5. `uv run ruff check .` y `uv run ruff format --check .` pasan sin errores.
6. `uv run mypy src` pasa sin errores (el paquete incluye `py.typed`).
7. El `pyproject.toml` declara las 4 dependencias de runtime con el marker correcto: `pywin32` solo instala en Windows (`sys_platform == "win32"`); en Linux no se instala.
8. El layout es `src/` (el paquete no es importable desde el raíz del repo sin instalación, evitando shadowing).
9. `uv.lock` queda versionado en git; `.gitignore` cubre cachés de herramientas y artefactos.

## Pasos de Implementación

1. **Estructura de directorios:**
   ```
   odin/
   ├── src/
   │   └── odin/
   │       ├── __init__.py      # __version__ = "0.1.0"
   │       ├── py.typed         # marker PEP 561
   │       └── cli.py           # stub: main() con --version/--help
   ├── tests/
   │   ├── __init__.py
   │   └── test_smoke.py
   ├── README.md                # título + descripción breve + quickstart mínimo
   ├── pyproject.toml
   ├── .gitignore               # actualizado
   └── .python-version          # existente: 3.14
   ```

2. **`pyproject.toml`** (reemplazar el contenido actual):
   - `[build-system]`: backend `hatchling`.
   - `[project]`: `name = "odin"`, `version = "0.1.0"`, descripción real (respaldo externo de bases Firebird con compresión 7z, transferencia SFTP y notificación por correo), `readme = "README.md"`, `requires-python = ">=3.14"`, `license`, `keywords`, `classifiers` (Development Status 3 - Alpha, Environment Console, Operating System Microsoft Windows :: Windows Server, POSIX :: Linux, Programming Language Python :: 3.14, Topic System :: Archiving :: Backup).
   - `dependencies`: `paramiko>=3.5`, `py7zr>=1.0`, `apscheduler>=3.11`, `pywin32>=310; sys_platform == "win32"` (confirmar versiones mínimas reales disponibles para Python 3.14; si alguna no existe aún, usar el piso mínimo disponible y registrar la decisión).
   - `[dependency-groups]` (PEP 735): `dev = ["pytest>=8", "pytest-cov", "ruff", "mypy"]`.
   - `[project.scripts]`: `odin = "odin.cli:main"`.
   - `[tool.hatch.build.targets.wheel]`: `packages = ["src/odin"]`.
   - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-ra --strict-markers"`.
   - `[tool.ruff]`: `line-length = 100`, `target-version = "py314"`; `[tool.ruff.lint]` con `select = ["E", "F", "I", "UP", "B", "SIM", "W"]` y `[tool.ruff.lint.isort]` con `known-first-party = ["odin"]`.
   - `[tool.mypy]`: `python_version = "3.14"`, `strict = true` (si `strict` genera fricción con librerías sin stubs, relajar a `disallow_untyped_defs` y registrar la decisión; paramiko/py7zr pueden carecer de stubs → usar `ignore_missing_imports` por módulo en `[[tool.mypy.overrides]]`).

3. **Stub de CLI (`src/odin/cli.py`):** función `main(argv: list[str] | None = None) -> int` con argparse, flags `--version` (imprime `odin <versión>`) y help por defecto; `if __name__ == "__main__": raise SystemExit(main())`. Tipado completo.

4. **Tests (`tests/test_smoke.py`):**
   - `import odin` y `odin.__version__ == "0.1.0"`.
   - `odin.cli.main(["--version"])` retorna 0 (capturando stdout con `capsys`).
   - Verificación de que el paquete instalado viene del layout `src/` (p. ej. `"src" not in odin.__file__` dentro de site-packages, o simplemente import exitoso).

5. **`.gitignore`:** agregar `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `uv.lock` NO (se versiona), manteniendo las entradas existentes.

6. **`README.md`:** título, descripción de una línea, requisitos (Python ≥ 3.14, uv, Firebird/gbak), quickstart mínimo (`uv sync`, `uv run pytest`, `uv run odin --version`). El README completo llega en el item 009.

7. **Verificación multiplataforma del lock:** `uv lock` resuelve para todas las plataformas por defecto; comprobar que el lock contiene la entrada de `pywin32` condicional sin romper Linux (`uv sync` en Linux no debe intentar instalarlo).

## Estrategia de Testing

- **Unit/humo (pytest):** import del paquete, versión, comportamiento del stub de CLI (exit code y salida). Sin servicios externos; todo local.
- **Estático:** `ruff check`, `ruff format --check`, `mypy src` como gates.
- **Instalación:** `uv sync` desde cero (borrar `.venv` si existe) y ejecución del console script.
- Cobertura no exigida en este item (se introducirá con lógica real en items siguientes).

## Dependencias

- **De roadmap/progress:** ninguna (primer item).
- **De entorno:** `uv` instalado (presente: 0.11.x), Python 3.14 (`.python-version` ya fijado), git.
- **Bloquea a:** items 002–009 (todos asumen esta estructura).

## Prerrequisitos de Testing

### Servicios Requeridos
- Ninguno. Este item no requiere bases de datos, SFTP, SMTP ni ningún servicio externo.

### Configuración de Entorno
- `uv` disponible en PATH (verificar con `uv --version`).
- Python 3.14 gestionado por uv (`.python-version = 3.14` ya existe; si falta el intérprete: `uv python install 3.14`).
- No se requieren variables de entorno ni secretos.
- No se requieren puertos libres.

### Checklist de Validación Manual
- [ ] **Build/entorno:** `rm -rf .venv && uv sync` completa sin errores y crea `uv.lock`.
- [ ] **Paquete importable:** `uv run python -c "import odin; print(odin.__version__)"` → `0.1.0`.
- [ ] **Aplicación corre:** `uv run odin --version` → `odin 0.1.0`, exit code 0; `uv run odin --help` muestra uso.
- [ ] **Tests pasan:** `uv run pytest -q` verde.
- [ ] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy src` sin errores.
- [ ] **Marker de plataforma:** `uv pip list` en Linux no incluye `pywin32`; el lock contiene la entrada condicional.
- [ ] **Layout src verificado:** `uv run python -c "import odin; print(odin.__file__)"` apunta a `.venv/.../site-packages` (no al raíz del repo).

### Resultados Esperados
- Archivos nuevos/versionados: `pyproject.toml` (reescrito), `src/odin/__init__.py`, `src/odin/py.typed`, `src/odin/cli.py`, `tests/__init__.py`, `tests/test_smoke.py`, `README.md` (actualizado), `.gitignore` (actualizado), `uv.lock` (nuevo, versionado).
- 3 tests de humo pasando.
- Console script `odin` operativo con `--version` y `--help`.

### Plantilla de Documentación de Validación

```markdown
## Validation Results
- [ ] `uv sync` desde cero exitoso (uv.lock generado)
- [ ] `import odin` → versión 0.1.0
- [ ] `odin --version` / `odin --help` → exit code 0
- [ ] `pytest -q` verde (3 tests)
- [ ] `ruff check` + `ruff format --check` + `mypy src` sin errores
- [ ] pywin32 ausente en Linux / presente en lock con marker
- [ ] Servicios externos: N/A
```

## Adaptaciones de Plantilla (documentadas)

- Se omite la sección de servicios externos/health checks de la plantilla estándar: el item es puramente de estructura local. Se reemplaza por la checklist de validación de entorno/build anterior.

## Decisions & Trade-offs

- **Compatibilidad Python 3.14 verificada (riesgo transversal cerrado para Linux):** con Python 3.14.4 y uv 0.11.17, `uv sync` resolvió sin problemas: `paramiko 5.0.0`, `py7zr 1.1.3`, `apscheduler 3.11.3`, `pytest 9.1.1`, `ruff 0.16.6`, `mypy 2.3.1`, `pywin32>=310` condicional. Falta confirmar en Windows (Item 009).
- **paramiko 5.x:** el piso `>=3.5` resolvió la major 5.0.0. Se mantiene el piso amplio; la API SFTP usada en la Etapa 4 deberá validarse contra la 5.x.
- **APScheduler 3.11.3 (serie 3.x):** el resolver no eligió la serie 4.x; la Etapa 6 debe programar contra la API 3.x (o reevaluar 4.x explícitamente en su momento).
- **mypy strict viable:** `strict = true` pasa sin fricción en el código propio; se usan `ignore_missing_imports` por módulo para `paramiko`, `py7zr` y `apscheduler` (sin stubs).
- **hatchling + layout src/:** funciona correctamente (build editable y wheel). Con instalación editable de uv, `odin.__file__` apunta a `src/odin/__init__.py`; el test de layout se implementó como verificación de resolución del módulo (alternativa permitida por la spec) en lugar de chequear `site-packages`.
- **Ruff excluye `.specify/` y `.opencode/`:** son scripts de Spec Kit/herramientas de terceros, no código del proyecto.
- **Classifiers trove:** no existe `Operating System :: Microsoft :: Windows :: Windows Server`; se usa `Operating System :: Microsoft :: Windows`.
- **Grupo dev vía PEP 735** (`[dependency-groups]`): uv lo instala por defecto con `uv sync`.

## Validation Results

- [x] `uv sync` desde cero exitoso (uv.lock generado, 85 paquetes)
- [x] `import odin` → versión 0.1.0
- [x] `odin --version` / `odin --help` → exit code 0
- [x] `pytest -q` verde (4 tests)
- [x] `ruff check` + `ruff format --check` + `mypy` sin errores
- [x] pywin32 ausente en Linux / presente en lock con marker `sys_platform == 'win32'`
- [x] Servicios externos: N/A

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md`: el entregable correspondiente de la Etapa 1 y la fila de la Etapa 1 en el resumen deben pasar de 📋 → 🚧 → ✅ según corresponda. Este paso es parte de `/speckit.aide.execute-item`.

## Próximo Paso

Iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.execute-item` con el número **001** para implementar este item.
