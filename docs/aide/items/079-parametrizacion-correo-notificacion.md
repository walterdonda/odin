# Item 079: Parametrización del correo de notificación (asunto, cuerpo y firma)

## Description

Hacer parametrizable el informe de correo de `odin run` y de cada ciclo del
scheduler: asunto, cuerpo (texto plano y HTML) y firma configurables desde el
JSON con placeholders `{clave}`, incluyendo el nombre de la instancia
(`databases[].name`), el motor de base de datos, el horario (legible para el
receptor), el estado y el contexto de entorno como tupla
**entidad cliente + entorno**. Se mantiene la garantía de siempre: el correo se
envía **siempre** (éxito/parcial/fallo), sin secretos (doble barrera con
`SecretMasker`) y sin adjuntar el backup.

Este item es el **diseño cerrado** de la sesión de grilling: define el contrato
de configuración, el mecanismo de plantillas y las decisiones de producto. La
implementación se descompone en los items del batch que arranque de una cola
nueva (ver Prerequisites).

## Acceptance Criteria

- [x] Bloque `notification` ampliado (todo opcional salvo lo actual, con
      defaults integrados): `subject`, `body_text`, `body_html`, `signature`
      (plantillas con placeholders), `contact` (string libre) y
      `log_tail_lines` con default **200** (antes 50). `to` documentado como
      lista de destinatarios separados por coma (hoy ya funciona así con
      `send_message`; no se añade override por instancia).
- [x] Bloque nuevo opcional a nivel raíz `environment: {"client", "name"}`;
      si falta, el correo no lleva prefijo de entorno (compatibilidad con
      configs actuales). Si una plantilla referencia `{cliente}`/`{entorno}` y
      el bloque no existe, la validación de configuración falla.
- [x] Placeholders disponibles (whitelist estricta, nombre español, sintaxis
      `{clave}`; placeholder desconocido → error de configuración al cargar):
      `{cliente}`, `{entorno}`, `{instancia}` (nombres de las bases de la
      corrida unidos por coma, truncando a 3 con ` +N`), `{motor}` (motores
      presentes sin duplicados), `{estado}` (ÉXITO/PARCIAL/FALLO), `{horario}`,
      `{zona_horaria}`, `{host}`, `{fecha}`, `{contacto}`, `{log}`, `{bases}`,
      `{servidores}`, `{totales}`.
- [x] Asunto por defecto:
      `[ODIN] [{cliente}-{entorno}] {estado} — respaldo de {instancia} ({fecha})`
      (sin prefijo si no hay `environment`); el estado siempre visible en el
      asunto (decisión de proyecto).
- [x] Horario **legible en español** para el receptor: renderer interno (sin
      dependencia nueva) que cubre los patrones comunes —"todos los días a las
      03:00 (America/Caracas)", "lunes a viernes a las 09:00 …", "el día 1 de
      cada mes a las 02:00 …"— y cae al cron crudo + zona IANA cuando el patrón
      no lo entiende. Corridas manuales (`odin run`): `{horario}` = "manual".
- [x] Multipart: `EmailMessage` con `text/plain; charset="utf-8"` +
      `text/html; charset="utf-8"` (`add_alternative`), cabecera
      `Content-Language: es-419`, HTML por defecto con tabla de resumen y el
      log en `<pre>`. Esto reemplaza deliberadamente la decisión "solo texto
      plano" del Item 040.
- [x] Firma por defecto parametrizable (campos ausentes se omiten):
      `ODIN · {cliente}-{entorno}` + línea de contacto si `notification.contact`
      existe; se aplica en ambas partes.
- [x] El scheduler pasa el contexto del job (schedule + timezone) al pipeline y
      al render (`PipelineCycleRunner` → `run_pipeline` → `render_report`);
      `odin run` no pasa contexto.
- [x] El enmascarado con `SecretMasker` se mantiene como segunda barrera sobre
      asunto y cuerpo ya templados; el correo nunca adjunta el backup.
- [x] Exit codes sin cambios (0/1/3/4): un SMTP caído sigue degradando 0 → 1.
- [x] Docs: `docs/configuration.md` §6, README ("Notificación por correo"),
      `examples/config.*.json` y docstrings de `notify.py`/`config.py`/
      `scheduler.py` alineados con el comportamiento nuevo.
- [x] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. `config.py`: ampliar `_NOTIFICATION_FIELDS`/`_parse_notification` con
   `contact`, `subject`, `body_text`, `body_html`, `signature`; nuevo
   `EnvironmentConfig` y bloque raíz `environment` (opcional, strings libres,
   campos desconocidos rechazados como el resto); subir default de
   `log_tail_lines` a 200; validar la whitelist de placeholders en
   `validate_semantics` (incluida la exigencia de `environment` cuando la
   plantilla usa `{cliente}`/`{entorno}`).
2. `notify.py`: función pura `render_template(template, values)` con
   reemplazo por whitelist; renderer `humanize_cron(schedule, timezone)`
   (módulo propio, p. ej. `src/odin/cron_phrase.py`, sin dependencias) con
   fallback a cron crudo; `render_report` gana el contexto del job
   (`schedule`/`timezone`/`manual`) y construye asunto/cuerpos/firma desde las
   plantillas (defaults integrados si el campo falta).
3. `EmailNotifier._build_message`: multipart UTF-8 + `Content-Language:
   es-419`; el `ReportMessage` pasa a llevar `body_text` + `body_html`.
4. `pipeline.py`/`scheduler.py`: parámetro de contexto de job a través de
   `run_pipeline`; `PipelineCycleRunner` entrega el schedule del job;
   `odin run` pasa contexto manual.
5. Tests: plantillas/whitelist/humanize (unidad), render multipart, truncado de
   instancias, exigencias semánticas de `environment`, enmascarado post-templado
   e integración SMTP con ambas partes en `tests/smtp_catcher.py`.
6. Documentación: `docs/configuration.md` §6, README, ejemplos y docstrings.

## Testing Strategy

- Unidad en `tests/test_notify.py` y `tests/test_config.py`: whitelist
  (desconocido → error), defaults integrados, asunto por defecto con/sin
  `environment`, truncado `+N`, horario legible por patrón y fallback a cron
  crudo, corrida manual = "manual", masking post-templado.
- Multipart: `EmailMessage` contiene ambas partes con charset explícito y
  `Content-Language`; el catcher SMTP (`tests/smtp_catcher.py`) parsea el
  mensaje real y verifica texto + HTML.
- Integración scheduler: `tests/test_scheduler_integration.py` con el correo
  de un ciclo que muestre horario legible y timezone del job.
- Gates completos del batch.

## Dependencies

- Items 039-048 (correo), 049-058 (scheduler, `PipelineCycleRunner` del Item
  054), `config.py`/`validate.py`, `docs/configuration.md` §6, README,
  `examples/config.*.json`.

## Decisions & Trade-offs

- **Plantillas inline en el JSON con defaults integrados** (vs. archivos
  externos `.txt`/`.html`): mantiene la filosofía "un solo JSON, validación
  estricta"; si el campo falta, se usa la plantilla actual, de modo que las
  configs existentes siguen funcionando sin cambios.
- **Whitelist estricta de placeholders** con error de configuración ante claves
  desconocidas, igual que los campos desconocidos del JSON; las llaves `{`/`}`
  quedan reservadas (sin mecanismo de escape).
- **Lista global de destinatarios sin override por instancia**: `to` separado
  por comas ya funciona hoy con `send_message` (verificado); el correo es uno
  por corrida, así que los destinatarios por instancia serían una unión difícil
  de explicar y más superficie de configuración.
- **`environment: {client, name}` opcional, strings libres**: sin enum de
  entornos para no limitar despliegues; si el bloque falta, sin prefijo
  (compatibilidad). La tupla identifica la instalación en el asunto.
- **Horario legible con renderer interno y fallback a cron crudo + zona** (vs.
  dependencia `cron_descriptor`): el proyecto es casi sin dependencias runtime;
  el renderer cubre los patrones cotidianos en español y para lo exótico el
  cron crudo sigue siendo exacto. Reemplaza la propuesta inicial de mostrar el
  cron "codificado".
- **Multipart con UTF-8 explícito y `Content-Language: es-419`**: reemplaza
  deliberadamente "solo texto plano" del Item 040; es-419 es el código estándar
  de español latinoamericano (es-417 no existe).
- **`log_tail_lines` default 200**: el receptor pidió conservar la mayor
  cantidad de log posible; 200 líneas enmascaradas es generoso sin acercarse a
  límites de tamaño de SMTP; configurable sin tope.
- **Contexto de job en el pipeline**: el render necesita el horario/zona del
  job que disparó el ciclo; `odin run` queda como "manual". No cambia exit
  codes ni la garantía de correo siempre.

## Evidencia de implementación

- **Render**: `render_template` con reemplazo literal por whitelist (valores con
  llaves literales, sin `str.format`); `render_report` gana `job` inyectable;
  firma aplicada siempre (separador `--`) en texto y HTML; HTML por defecto
  escapa valores (`html.escape`).
- **Hallazgo Python 3.14**: `EmailMessage.set_content`/`add_alternative`
  limpian la cabecera `Content-Language` si se fija antes; se asigna después
  del contenido (documentado en el docstring de `_build_message`).
- **`to` multi-destinatario**: verificado en implementación — el parser
  rechazaba listas (regex de un solo email), así que `notification.to` ahora
  acepta y normaliza varios emails separados por coma; el `from` sigue siendo
  un solo email.
- **Horario legible**: `src/odin/cron_phrase.py` (nuevo, sin dependencias) —
  diario, días de semana (entero, lista, rango; pluralización correcta
  "los domingos"), día del mes (simple y lista) y mes+día; pasos/rangos
  de minuto u hora y combinaciones DOM+DOW caen al cron crudo + zona.
- **Tests**: 15 tests nuevos en `tests/test_cron_phrase.py`; `tests/test_notify.py`
  ampliado (multipart/UTF-8/`Content-Language`, plantillas, entorno, firma,
  horario, truncado `+N`); `tests/test_config.py` ampliado (multi-`to`,
  plantillas, whitelist, bloque `environment`); `tests/smtp_catcher.py` gana
  `plain_body()` (la policy default no soporta `get_content()` en
  multipart/alternative) y las integraciones (notify, scheduler, foreground,
  service linux/windows) la usan; `test_scheduler_integration` verifica el
  horario legible del job en el correo.
- **Gates**: `uv run pytest -q` → **794 passed + 7 skipped** (los skips son
  gbak/Firebird ausentes, demos gated y SCM de Windows);
  `uv run ruff check src/odin tests` → All checks passed;
  `uv run mypy src/odin` → Success (24 source files).
  `uv run odin validate --config examples/config.linux.json` → exit 0
  (0 errores, 3 advertencias de plantilla esperadas).
- **Docs**: `docs/configuration.md` (§2 tabla, §6 con §6.4 placeholders y §6.5
  `environment`, §12 ejemplo completo), README (bloques del JSON, paso 6,
  informe por correo), `examples/config.{linux,windows}.json` con bloque
  `environment` + `contact`, y `reference/GLOSSARY.md` con los cinco términos
  del diseño.

## Prerequisites

- `docs/aide/progress.md` actualizado a ✅ (Item 079 con entregables y
  evidencia).
- Se implementó **directamente** con `/speckit.aide.execute-item` (la
  `queue-008` estaba agotada); para trabajo futuro nuevo, crear la cola con
  `/speckit.aide.create-queue` en una sesión nueva.
