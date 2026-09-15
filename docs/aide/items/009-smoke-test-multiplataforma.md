# Item 009: Smoke test multiplataforma del ciclo de desarrollo

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 009. Etapa 1 del roadmap.

## Descripción

Validar el ciclo completo de desarrollo en las dos plataformas objetivo: Linux LTS y Windows Server. El objetivo es garantizar que el proceso de desarrollo (`uv sync`, `pytest`, `odin validate`) es idéntico y funcional en ambos sistemas operativos, asegurando que el código fuente y la resolución de dependencias sean verdaderamente OS-agnósticos.

## Criterios de Aceptación

1.  **Ciclo de desarrollo funcional en Linux**:
    *   `uv sync` completa sin errores.
    *   `uv run pytest` pasa con todos los tests (incluyendo `tests/test_deps_compat.py`).
    *   `uv run odin validate --config examples/config.linux.json` devuelve exit code 0.
2.  **Ciclo de desarrollo funcional en Windows** (simulado o real):
    *   `uv sync` completa sin errores.
    *   `uv run pytest` pasa con todos los tests.
    *   `uv run odin validate --config examples/config.windows.json` devuelve exit code 0.
3.  **Documentación de Quickstart**: Actualizar `README.md` con los comandos exactos de validación para cada plataforma.
4.  **Verificación de resolución de dependencias**: Confirmación de que `pywin32` se resuelve y marca correctamente para Windows mediante la lectura estática del `uv.lock` (evidencia ya aportada en Item 008).

## Implementación

1.  **Re-verificación en Linux**: Ejecutar la suite de comandos para asegurar que el estado actual es verde.
2.  **Preparación de evidencia para Windows**: (Dado el entorno actual) Utilizar la evidencia estática del `uv.lock` (wheels `cp314` para `win32/amd64/arm64`) para validar la resolución en Windows.
3.  **Actualización de README.md**: Añadir o refinar la sección de "Quickstart" o "Ejemplos de configuración" con los comandos de validación por plataforma.
4.  **Actualización de `docs/aide/progress.md`**: Marcar la Etapa 1 como completada con el cierre del Item 009.

## Estrategia de Testing

*   **Test de integración (Linux)**: Ejecución real de `odin validate` contra el archivo de configuración de Linux.
*   **Test de integración (Windows - Simulado)**: Ejecución de `odin validate` contra el archivo de configuración de Windows en el entorno Linux (verificando que el parser de rutas y la lógica de markers de plataforma funcionen).
*   **Test de resolución (Estático)**: Verificación de la existencia de archivos de plataforma Windows en el `uv.lock`.

## Dependencias

*   `uv` instalado y operativo.
*   Python 3.14.

## Prerrequisitos de Testing

**Requeridos**
*   Entorno Linux LTS (actual).
*   Acceso a `uv` y `pytest`.

**Configuración de Entorno**
*   Archivo `examples/config.linux.json` existente y válido.
*   Archivo `examples/config.windows.json` existente y válido.

**Manual Validation Checklist**
*   [ ] **Build succeeds**: `uv sync` sin errores.
*   [ $\text{pytest}$ passes**: `uv run pytest` verde.
*   [ ] **Application runs (Linux)**: `uv run odin validate --config examples/config.linux.json` exit 0.
*   [ ] **Application runs (Windows-compatible logic)**: `uv run odin validate --config examples/config.windows.json` exit 0.
*   [ ] **Data verified**: El `uv.lock` contiene los wheels `cp314` para `pywin32` (verificación vía `grep`).

**Expected Outcomes**
*   `README.md` actualizado y funcional para ambos sistemas.
*   Suite de tests completa (~)201+ tests pasando.
*   Etapa 1 del roadmap marcada como completada ✅.

## Decisiones & Trade-offs

> **Decisiones durante la implementación:**
> - **Validación de Windows en Linux:** Se utilizó la capacidad del parser de detectar rutas con "sabor Windows" (`D:/Backups/odin`) para validar la lógica sin necesidad de un entorno Windows real, cumpliendo el criterio de validación de coherencia OS-agnóstica.
> - **Verificación de dependencias:** Se utilizó `grep` sobre `uv.lock` para confirmar la presencia de wheels `cp314` para `pywin32` en plataformas `win32`, `amd64` y `arm64`, garantizando la resolución para Windows.
> - **2026-09-15 — Linux cerrado por el Item 071:** el ciclo `uv sync` + `uv run pytest` + `odin validate` quedó automatizado en el gate único `scripts/verify.py` (evidencia en `docs/aide/items/071-script-verificacion-multiplataforma.md`). El item **no** se marca completo: la confirmación en Windows Server real queda para el Item 074 (CI del Item 073 y/o runbook §8 de `docs/service.md`).

## Recordatorio de Completado

> **IMPORTANTE:** Al completar este item, actualizar `docs/aide/progress.md` (**solo** las filas correspondientes al Item 009, según la regla de scoping):
>
> - Criterio de aceptación de la Etapa 1 "[x] `uv sync` + `uv run pytest` funcionando en Linux y Windows": **ENRIQUECER** con la nota de que se ha verificado en Linux y se tiene evidencia estática de resolución para Windows (pantalla de `uv.lock`).
> - Línea "**Última actualización:**" → fecha del día + "(Item 009 completo ✅)".
