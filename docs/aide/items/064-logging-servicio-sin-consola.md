# Item 064: Logging persistente del servicio sin consola

## Description

Agregar el modo servicio al logging para que el proceso residente (bajo el SCM
de Windows o systemd, sin handles de consola) registre **solo** a archivo y no
falle por salidas de consola perdidas.

- `setup_logging(config, *, console: bool = True)` (`log.py:149`):
  - `console=True` (default): comportamiento actual intacto (consola +
    archivo rotado), del que depende `odin service run` en primer plano.
  - `console=False`: **sin** `StreamHandler`; un único `RotatingFileHandler`
    (5 MiB × 5 backups) sobre `<resolved_log_dir>/odin.log` con el
    `MaskingFilter` aplicado y el nivel de `local.log_level`.
  - La idempotencia se mantiene: re-invocar cierra y remueve los handlers
    previos (recarga en caliente del Item 055) sin duplicar salidas.
- `redirect_stdio_to_log(path)` en `log.py`: context manager que reemplaza
  `sys.stdout` y `sys.stderr` por un writer que **agrega** al archivo indicado
  (el mismo `odin.log`) y restaura ambos streams al salir, incluso ante
  excepción. Si el archivo no es escribible (`OSError`, incluida una ruta que
  es directorio), el writer descarta el texto (sumidero seguro): un `print`
  perdido en un servicio sin consola no debe tumbar el proceso. Expone
  `write`/`flush`/`isatty()`/`writelines` para ser un file-like razonable; no
  aplica enmascarado (la barrera de secretos del log estructurado sigue siendo
  el `MaskingFilter` de los handlers).
- Exportar `redirect_stdio_to_log` en `__all__` de `log.py`. El consumo real
  (ServiceRunner del Item 065 y `SvcDoRun` del Item 061) llega con el Item 065;
  acá se implementa y prueba el helper.

## Acceptance Criteria

- [x] `setup_logging(config, console=False)` deja exactamente un handler: un
      `RotatingFileHandler` con la rotación existente; ningún
      `StreamHandler` de consola.
- [x] Con `console=False` el nivel de `local.log_level` aplica al file handler
      y los mensajes con secretos quedan enmascarados en el archivo.
- [x] `setup_logging(config)` (default) conserva el comportamiento actual: un
      file handler + un stream handler, 2 handlers en total.
- [x] Re-invocar `setup_logging` con `console=False` es idempotente: sigue
      habiendo un solo handler y no se duplican líneas.
- [x] `redirect_stdio_to_log(path)`: un `print` dentro del bloque aparece en
      `path`; `sys.stdout`/`sys.stderr` quedan restaurados al salir (también
      con excepción); con un destino no escribible no propaga `OSError` ni
      escribe nada.
- [x] El helper devuelve/yields la ruta objetivo y funciona con `print(...,
      file=sys.stderr)`.
- [x] `odin service run` en primer plano conserva la consola (sin cambios de
      comportamiento; los tests existentes de `tests/test_cli.py` siguen
      verdes).
- [x] Tests en `tests/test_log.py` para `console=False`, idempotencia y el
      context manager (redirección, restauración, destino no escribible).
- [x] Gates del item en verde: `uv run pytest tests/test_log.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Extender `setup_logging` con el parámetro `console` y condicionar el
   `StreamHandler`.
2. Escribir el writer file-like y el context manager `redirect_stdio_to_log`
   (con `try/except OSError` de descarte); exportarlo en `__all__`.
3. Ampliar `tests/test_log.py` con los casos nuevos (fixture `tmp_path` y el
   fixture existente que limpia el logger).
4. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_log.py -q`.
- Handlers: contar tipos (`RotatingFileHandler`, `logging.StreamHandler`
  exacto) tras `setup_logging(config, console=False)`; verificar el archivo con
  una línea enmascarada.
- Redirección: `with redirect_stdio_to_log(path): print(...)` y verificar el
  contenido del archivo y que `sys.stdout is` el original al salir; el caso de
  excepción con `pytest.raises`; el destino no escribible con una ruta que es
  directorio (o modo sin escritura).
- No se abre ninguna consola real: los tests corren bajo la captura de pytest.
- Gates: ruff y mypy completos.

## Dependencies

- Item 004 (`setup_logging`, `MaskingFilter`, rotación) y `local.resolved_log_dir`.
- Item 055 (idempotencia usada por la recarga en caliente).
- Consumo posterior: Item 065 (`ServiceRunner`) y Item 061 (`SvcDoRun`).
- Insumos: `queue-007.md` (Lote B) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **La consola es un parámetro, no un modo separado**: `console=True` conserva
  exactamente el contrato del Item 004 (dos handlers) del que dependen
  `odin run`/`odin service run` en primer plano y la recarga en caliente; el
  modo residente pide `console=False` explícitamente. No se introduce un
  "modo servicio" global en el logger (estado oculto difícil de testear).
- **`_LogStream` compatible estructuralmente con `TextIO`**: el writer expone
  `write`/`writelines`/`flush`/`isatty`/`encoding`/`errors`, así que mypy lo
  acepta como `sys.stdout` sin `type: ignore` (los comentarios previstos
  resultaron "unused-ignore" y se retiraron). Si el proyecto tipa el stream
  más estrictamente, el contrato ya está completo.
- **Cada `write` abre y cierra el archivo en modo append**: evita retener un
  file descriptor durante toda la vida del servicio y hace que el caso "no
  escribible" sea un `OSError` capturado por escritura. El costo (una apertura
  por línea impresa) es irrelevante: solo pasan por acá `print`s perdidos.
- **Solo se captura `OSError`**: un destino no escribible (permisos, ruta que
  es directorio, padre inexistente) descarta el texto en silencio —el
  sumidero seguro que pide el item—; cualquier otra excepción es un bug y no
  debe ocultarse.
- **El writer no enmascara**: el enmascarado de secretos sigue siendo la
  barrera del `MaskingFilter` de los handlers del logger. Duplicar el masker
  en el writer obligaría a cablear la configuración en el context manager y a
  mantener dos rutas de enmascarado; el contrato de `print` crudo no es una
  vía que ODIN use para volcar secretos (los resúmenes de la CLI imprimen
  cadenas ya enmascaradas).
- **`flush()` no-op**: al no retener un handle, no hay buffer que vaciar; los
  streams que hacen `print(..., flush=True)` funcionan igual.

**Evidencia:** `uv run pytest tests/test_log.py -q` → **50 passed** (9 casos
nuevos: único file handler con rotación y máscara en `console=False`, nivel
aplicado, idempotencia, default de dos handlers, redirección a archivo con
restauración de ambos streams, restauración ante excepción, destino que es
directorio, padre inexistente y el valor devuelto por el context manager);
`uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin`
→ Success: no issues found in 18 source files. El comportamiento de
`odin service run` en primer plano no cambió: `tests/test_cli.py` completo →
94 passed.

## Prerequisites

- No requiere systemd, Windows ni pywin32.
- `docs/aide/progress.md` debe reflejar el avance del entregable de logging
  persistente al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.
