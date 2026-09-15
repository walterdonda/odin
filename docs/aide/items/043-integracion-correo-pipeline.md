# Item 043: Integración del correo en `odin run` (siempre, SMTP caído no crashea)

## Description

Agregar la fase de notificación a `run_pipeline` (`src/odin/pipeline.py`): al terminar las tres fases acumuladas (respaldo → compresión → transferencia) y con el lote final ya construido, renderizar el informe (Item 040) y enviarlo con un `EmailNotifier` inyectable (default `EmailNotifier.from_config(config)`). `PipelineResult` gana `notification: NotificationResult | None`. El correo se envía **siempre**: éxito total, fallo parcial, fallo total, lote no ejecutado (`error_message`) y lote vacío. La cola de log (Item 041) se captura durante la ejecución de las fases y se pasa al render. Un SMTP caído no produce crash ni excepción: queda en el log y en `NotificationResult.error_message`, y el exit code de una corrida por lo demás exitosa no puede ser 0 (se degrada 0 → 1, Item 044).

## Acceptance Criteria

- [ ] `run_pipeline` acepta `notifier: EmailNotifier | None = None`; sin inyección construye `EmailNotifier.from_config(config)`.
- [ ] `PipelineResult` expone `notification: NotificationResult | None` (con default `None` para construcciones manuales).
- [ ] El informe se envía exactamente una vez por corrida, también con lote fallido (`error_message`), lote vacío y fallo total.
- [ ] La captura de la cola de log usa `config.notification.log_tail_lines` + `SecretMasker.from_config(config)` y las líneas viajan al render como `log_tail`.
- [ ] Un notifier cuyo `send` devuelve fallo no interrumpe el pipeline: el resultado queda en `PipelineResult.notification` y se loguea.
- [ ] Una excepción imprevista del notifier tampoco interrumpe el retorno del pipeline (red de seguridad que produce `NotificationResult(success=False, ...)`).
- [ ] `tests/test_cli.py` (`_install_fake_executor`) parchea `odin.pipeline.EmailNotifier` para que los tests existentes no intenten SMTP real.
- [ ] Tests de pipeline con notifier doble: una invocación, contenido renderizado (estados ÉXITO/PARCIAL/FALLO), cola de log incluida, notifier fallido no interrumpe.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Ampliar `PipelineResult` con `notification: NotificationResult | None = None` (import de `odin.notify` fuera del ciclo de importación: `notify` ya importa `pipeline` solo bajo `TYPE_CHECKING`).
2. Envolver las tres fases de `run_pipeline` en `capture_log_tail(config.notification.log_tail_lines, SecretMasker.from_config(config))` y recuperar `tail.lines` al salir.
3. Renderizar con `render_report(config, result, log_tail=lines)` y enviar con el notifier inyectado o el default.
4. Encapsular `send` en una red de seguridad que traduzca una excepción imprevista en `NotificationResult` fallido (sin propagar), documentando la decisión en el docstring del módulo y de `run_pipeline`.
5. Ajustar `_install_fake_executor` en `tests/test_cli.py` para parchear `odin.pipeline.EmailNotifier` con un doble de éxito por defecto.
6. Agregar tests de pipeline con `FakeNotifier` (registra llamadas; permite devolver fallo y lanzar excepción).

## Testing Strategy

- `tests/test_pipeline.py`: `FakeNotifier` que guarda el `ReportMessage` recibido; se verifica una invocación por corrida, asunto con estado correcto, cuerpo con las bases, envío en lote vacío/error de lote/fallo total, líneas de log presentes en el cuerpo y aislamiento ante notifier fallido o que lanza.
- `tests/test_cli.py`: los tests existentes siguen verdes con el doble instalado (sin SMTP real).
- Gates: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Items 039-042 (`src/odin/notify.py`, `capture_log_tail` en `src/odin/log.py`), Item 035 (`PipelineResult`).

## Decisions & Trade-offs

- **Notifier default desde la config e inyectable**: `run_pipeline` construye `EmailNotifier.from_config(config)` solo si no recibe uno; los tests doblan la clase (`_OfflineNotifier` autouse en `tests/test_pipeline.py`, `_install_fake_notifier` en `tests/test_cli.py`) para que ninguna corrida de test abra SMTP real. La construcción ocurre antes de las fases (es barata y no toca la red).
- **Envío fuera de la captura de cola**: `capture_log_tail` envuelve solo las tres fases; el render y el `send` corren después de recuperar `tail.lines` (los logs del propio envío no forman parte del informe que se está enviando). La doble barrera se conserva: el `TailBufferHandler` enmascara al capturar y `render_report` vuelve a enmascarar el texto completo.
- **Red de seguridad `except Exception` en `_send_report`**: `EmailNotifier.send` ya encapsula los errores SMTP esperados; la capa extra garantiza el invariante "SMTP caído no crashea" incluso ante un fallo imprevisto del notifier, produciendo `NotificationResult(success=False, error_message=...)` en vez de propagar. El destinatario se toma de `config.notification.to` (no del doble) para no depender de su superficie.
- **`notification: NotificationResult | None = None`**: default que preserva las construcciones manuales de `PipelineResult` (tests de render del Item 042); el pipeline real siempre lo llena porque el correo se envía siempre.
- **Éxito del pipeline ajeno al correo**: `backup.success` sigue reflejando solo las fases de datos; el desenlace del correo vive en `notification` y la degradación del exit code es responsabilidad de la CLI (Item 044), manteniendo el pipeline reutilizable por el scheduler (Etapa 6).

**Evidencia:** `uv run pytest tests/test_pipeline.py tests/test_cli.py tests/test_notify.py -q` → 79 passed (8 tests nuevos en `tests/test_pipeline.py`: una invocación con contenido renderizado, fallo total, lote no ejecutado, lote vacío, notifier fallido, notifier que lanza, cola de log incluida y cola deshabilitada); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success. Los 6 tests previos de pipeline siguen verdes sin tocar SMTP real (0.2 s).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
