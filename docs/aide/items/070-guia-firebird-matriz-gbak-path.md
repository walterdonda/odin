# Item 070: Ejecución de la matriz, guía `docs/firebird.md` y `gbak_path` por versión

## Description

Ejecutar la matriz del Item 069 en el host y registrar la evidencia (versión,
imagen/digest, versión de `gbak`, tamaño del `.fbk`, resultado del restore y
duración; sumar 3.0/4.0 si el costo es bajo), y escribir `docs/firebird.md`
como guía de compatibilidad y de `gbak_path` por versión.

Contenido mínimo de `docs/firebird.md`:

- **Matriz de compatibilidad** (2.5, 3.0, 4.0, 5.0, 6.x) con la evidencia
  ejecutada y la **regla de familia**: `gbak` de la misma versión mayor que la
  base; un cliente 3+ no habla con un servidor 2.5 ni viceversa.
- **Guía de `gbak_path`**: auto-detección de `gbak_finder` por SO y versión,
  override por base (`databases[].gbak_path`), convivencia de varias
  instalaciones Firebird y ejemplos JSON Linux/Windows.
- **Cadenas de conexión y charset** por versión.
- **Incompatibilidades encontradas**: password de 2.5 limitado a 8 bytes
  significativos, convenciones de las imágenes Docker por familia, diferencias
  de switches de `gbak`, charset fijo UTF8 de la imagen 2.5, etc.
- **Procedimiento para reproducir la matriz localmente** (Docker + variables
  `ODIN_FIREBIRD_*`).
- **Recomendación por tipo de despliegue**.

Ajustar `src/odin/gbak_finder.py`/`validate.py`/mensajes **solo si la matriz
revela un hueco real** (p. ej. una ruta típica no buscada), con sus tests.
Enlazar la guía desde el README y registrar el avance (no el cierre de la
etapa) en `docs/aide/progress.md`.

## Acceptance Criteria

- [x] Matriz ejecutada con evidencia registrada por fila: imagen/digest,
      versión de `gbak`, tamaño del `.fbk`, restore (filas) y duración,
      incluida la fila 6.x best-effort (o su skip justificado).
- [x] `docs/firebird.md` existe con: matriz de compatibilidad y regla de
      familia; guía de `gbak_path` (auto-detección, override, convivencia,
      ejemplos Linux/Windows); conexión/charset por versión;
      incompatibilidades; reproducción local con `ODIN_FIREBIRD_*`; y
      recomendación por despliegue.
- [x] Cada afirmación está contrastada con el código y con la ejecución real
      (sin afirmar rutas/comandos que no existan).
- [x] Si la matriz revela un hueco real en `gbak_finder`/`validate`, se
      corrige con su test; si no, se deja constancia de que no hubo cambios de
      código (o solo del cambio justificado).
- [x] `README.md` enlaza `docs/firebird.md`.
- [x] `docs/aide/progress.md` registra el avance del entregable de matriz y
      guía (sin cerrar la Etapa 8).
- [x] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. Correr la matriz del Item 069 y anotar la evidencia (versión de `gbak` por
   imagen, `.fbk`, filas restauradas, tiempos).
2. Revisar `src/odin/gbak_finder.py` y `src/odin/validate.py` contra las
   rutas/versiones observadas; corregir el hueco real con test.
3. Escribir `docs/firebird.md` con todas las secciones del item.
4. Enlazar la guía desde `README.md` y registrar el avance en
   `docs/aide/progress.md`.
5. Correr los gates y documentar decisiones/evidencia en "Decisions &
   Trade-offs".

## Testing Strategy

- `uv run pytest tests/test_firebird_matrix.py -q -m integration` → evidencia
  de la matriz.
- `uv run pytest tests/test_gbak_finder.py -q` (y `tests/test_validate.py` si
  se toca `validate.py`) → cambios de código cubiertos.
- `uv run pytest` completo + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin`.
- Verificación documental: cada comando/ruta de `docs/firebird.md` contrastado
  con `--help`/código y enlaces del README existentes.

## Dependencies

- Item 069 (banco de integración y helper de contenedor) y su evidencia.
- `src/odin/gbak_finder.py`, `src/odin/validate.py`, `src/odin/backup.py` y
  `README.md`.
- Docker con las imágenes de la matriz; `gbak` del host no requerido.

## Decisions & Trade-offs

- **Fila 4.0 sumada a la matriz**: la imagen `firebirdsql/firebird:4.0.5`
  existía para amd64 y comparte toda la convención de la familia moderna, así
  que la evidencia de la matriz quedó 2.5/3.0/4.0/5.0/6.0 (cinco filas) con
  costo bajo; la fila 6.x sigue best-effort.
- **Hueco real corregido**: la auto-detección no buscaba
  `/usr/local/firebird`, el prefijo por defecto de la instalación por tarball
  (la que usa la imagen 2.5). Se agregó a `_POSIX_ROOTS` y se cubrió con
  `test_find_gbak_linux_tarball_prefix` (sin estar en `PATH`). No aparecieron
  otros huecos: `validate.py` no se tocó y sus severidades/mensajes se
  documentaron tal como están (INFO/null, ERROR/directorio, WARNING/inexistente
  o no ejecutable, OK).
- **Incompatibilidades verificadas de primera mano**: se levantaron
  contenedores 2.5 y 5.0 en una red Docker compartida y se probaron los cruces
  reales (no solo la regla teórica): `gbak` 5.0 → servidor 2.5 falla con
  `invalid request BLR … data operation not supported`; `gbak` 2.5 → servidor
  5.0 falla con `connection rejected by remote interface`; `gbak` 2.5 no lee un
  `.fbk` de 5.0 (`Expected backup version 1..9. Found 11`); dentro de la
  familia moderna, `gbak` 5.0 respaldó servidores 3.0/4.0 y restauró un `.fbk`
  de 2.5 (tolerancia hacia atrás observada, documentada como *no* soportada).
  Los mensajes textuales quedaron en `docs/firebird.md` §2.
- **Guía contrastada con el código, no con recuerdos**: el orden de rutas de
  `gbak_finder`, la precedencia `databases[].gbak_path` > ejecutor >
  auto-detección (`backup.py`), las severidades de `validate`, el default
  `local.gbak_timeout_sec=7200` y que `charset` no se pasa a `gbak` se
  verificaron leyendo las fuentes antes de redactar. No se afirmó ninguna ruta
  o comando no existente.
- **README con dos enlaces**: en Requisitos (regla de familia) y en el paso 1
  de `odin run` (resolución de `gbak`), para que la guía sea alcanzable desde
  la operación diaria, sin duplicar su contenido.
- **`progress.md` sin cerrar la Etapa 8**: se marcó ✅ el entregable de matriz
  y guía, se actualizó "Última actualización" y "Próximo Paso" (Lote B,
  items 071-072); la etapa sigue 🚧 y los criterios 1-8 se cierran en el Item
  078.

**Evidencia:** `uv run pytest tests/test_firebird_matrix.py -q -m integration
-s` → **5 passed in 23.31 s** (2.5.9 LI-V2.5.9.27139 UTF8 2560 B; 3.0.9
LI-V3.0.9.33560 WIN1252 1536 B; 4.0.5 LI-V4.0.5.3140 ISO8859_1 1536 B; 5.0.4
LI-V5.0.4.1812 UTF8 1536 B; 6.0-snapshot LI-T6.0.0.2177 UTF8 3584 B; 3/3
filas restauradas en las cinco). `uv run pytest tests/test_gbak_finder.py -q` →
**4 passed**. `uv run pytest tests/test_backup_integration.py
tests/test_notify_integration.py -q` → **4 passed in 8.00 s**. Gates finales:
`uv run pytest -q` → **631 passed + 3 skipped in 48.87 s**; `uv run ruff check
src/odin tests` → All checks passed; `uv run mypy src/odin` → Success: no
issues found in 19 source files. `docs/firebird.md` creado (matriz, regla de
familia con mensajes reales, `gbak_path`, conexión/charset, incompatibilidades,
reproducción local y recomendaciones), enlazado desde `README.md`, y
`docs/aide/progress.md` con el entregable ✅, la cabecera y el próximo paso
hacia el Lote B.

## Prerequisites

- Los tests de la matriz son skip-safe sin Docker.
- No cierra la Etapa 8 (el cierre es el Item 078): solo registra el avance.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.
