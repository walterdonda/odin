# Item 041: Cola de log del informe (`notification.log_tail_lines`) y enmascarado del correo

## Description

Implementar en `src/odin/log.py` un `TailBufferHandler` (subclase de `logging.Handler` con `collections.deque(maxlen=N)`) que capture las últimas `notification.log_tail_lines` líneas ya formateadas y enmascaradas, y los helpers para adjuntarlo/removerlo del logger `odin` (context manager recomendado). `log_tail_lines == 0` desactiva la cola. La integración en la fase de notificación del pipeline corresponde al Item 043; acá se entrega el handler, el enmascarado del buffer y su superficie de tests.

## Acceptance Criteria

- [ ] `TailBufferHandler(maxlen, masker=None)` captura las líneas formateadas en un `deque(maxlen)`; expone las líneas capturadas y `clear()`.
- [ ] Con `masker` aplicado, el buffer nunca retiene secretos (segunda barrera propia, independiente del orden de handlers).
- [ ] Helpers/context manager para adjuntar y remover el handler del logger `odin`; `log_tail_lines == 0` no captura nada (handler desactivado).
- [ ] El buffer no retiene texto previo al attach (deque nuevo por captura) y respeta `maxlen`.
- [ ] El entorno de tests puede usarlo sin `setup_logging` y sin fugas entre tests (remoción garantizada).
- [ ] `__all__` de `log.py` actualizado y docstring del módulo coherente.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Agregar `TailBufferHandler` a `src/odin/log.py`: `emit` formatea el record, aplica `MaskingFilter` si hay masker y appendea al deque.
2. Exponer `lines` (tupla inmutable) y `clear()`.
3. Implementar `capture_log_tail(maxlen, masker=None, *, logger=None)` como context manager `contextlib.contextmanager`: crea el handler, lo adjunta al logger `odin` y lo remueve en `finally`; con `maxlen <= 0` no captura.
4. Actualizar `__all__` y el docstring del módulo (la frase del enmascarado "para los correos de la Etapa 5" deja de ser futuro).
5. Verificar que el handler usa el mismo `LOG_FORMAT` que el resto de handlers.

## Testing Strategy

- `tests/test_log.py`: `maxlen` respetado (últimas N y orden), sin texto previo al attach, `maxlen=0` vacío, secretos enmascarados (con `MaskingFilter` real y con `setup_logging`), remoción del logger al salir del context manager, idempotencia ante excepciones dentro del bloque.
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- `src/odin/log.py` (`SecretMasker`/`MaskingFilter`, Item 004), `notification.log_tail_lines` (Item 002). Consumidor: Item 043.

## Decisions & Trade-offs

- **`deque(maxlen)`**: memoria acotada y descarte O(1) de la línea más antigua; no hay recorte ni copias al capturar.
- **`MaskingFilter` propio del handler**: el filtro existente muta el `LogRecord` compartido y el resultado depende del orden de handlers; con el filtro embebido (mismo `SecretMasker`) el buffer queda enmascarado con independencia de ese orden. Es la barrera del buffer, complementaria al enmascarado final del render (Item 040).
- **Context manager con remoción en `finally`** más `attach_tail_buffer`/`detach_tail_buffer` como helpers de bajo nivel: la captura no puede quedar colgada del logger `odin` si el bloque falla.
- **`maxlen <= 0` no adjunta**: "desactivado" es costo cero y `lines` queda vacío; el handler con `deque(maxlen=0)` tampoco retiene nada por construcción.
- **`LOG_FORMAT` compartido** con consola/archivo: las líneas del correo son las mismas que quedaron en `odin.log`, con timestamp y nivel.
- **Integración diferida al Item 043**: `capture_log_tail` se usará alrededor de la corrida del pipeline; acá se entrega el mecanismo y su contrato (`lines` -> `render_report(log_tail=...)`).

**Evidencia:** `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success; `uv run pytest tests/test_log.py -q` → 41 passed (11 nuevos: `maxlen`, orden, sin texto previo, formato, `maxlen=0`, enmascarado propio, `clear`, remoción en salida y con excepción, helpers y `setup_logging` real sin fugas de secretos).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
