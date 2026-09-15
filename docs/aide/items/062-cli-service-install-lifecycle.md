# Item 062: CLI `odin service install|uninstall|start|stop`

## Description

Registrar las cuatro acciones nuevas del modo residente en el subcomando
`service` de la CLI y despacharlas a los gestores del Item 059-061.

- Parser (`build_parser`, `cli.py:190-256`): cuatro subparsers nuevos bajo
  `service` (`install`, `uninstall`, `start`, `stop`), cada uno con `--config`
  opcional, resuelto con `_resolve_config_source` (`--config` con precedencia
  sobre `ODIN_CONFIG`, como el resto de subcomandos). Actualizar la
  descripción del parser `service` y el docstring del módulo, que hoy anuncian
  `install/start/stop` como "Etapa 7" futura.
- `install` (handler `_cmd_service_install`):
  - **Exige** una fuente de configuración: sin `--config`/`ODIN_CONFIG` →
    `EXIT_CONFIG` (2) con el mensaje estándar y sin construir el gestor.
  - Carga la configuración (`_load_config_or_report`: `ConfigError` → 2) y la
    valida con `validate_config` (Item 006): con hallazgos **ERROR** de
    entorno/estructura → 2 e **instalación abortada** (se imprime el reporte
    con `_print_report`); las advertencias no bloquean.
  - Construye el `ServiceSpec` (Item 059) con `config_path` **absoluta**
    (`config.config_path.absolute()`) y el ejecutable resuelto a ruta absoluta
    cuando se puede (`_service_executable`: `sys.argv[0]` existente o
    `shutil.which("odin")`; último recurso `"odin"` — systemd rechaza un
    `ExecStart` relativo, el gestor lanza `ServiceError` claro si no hay ruta).
  - Construye el gestor con `create_service_manager(<config absoluta>)`
    (`manager_factory` inyectable, como `service_factory` en
    `_cmd_service_run`) e invoca `install(spec)`; imprime el mensaje devuelto
    (incluida la guía sin permisos del Item 060) y los pasos siguientes por
    plataforma (`odin service start` / `systemctl`).
  - `ServiceError` (incluida `ServiceUnsupportedError`) → 1 con el motivo en
    stderr.
- `uninstall`/`start`/`stop` (handler común `_cmd_service_lifecycle`): operan
  por nombre fijo `odin` con `--config` **opcional**. No cargan la
  configuración: si la fuente existe se resuelve a absoluta para construir el
  gestor; si no, se usa un centinela absoluto (estas operaciones no consumen
  la ruta, pero el contrato del gestor exige una absoluta). Cada acción
  devuelve 0 con el mensaje del gestor o 1 (`ServiceError`) con el motivo en
  stderr.

## Acceptance Criteria

- [x] El parser registra `install`, `uninstall`, `start` y `stop` bajo
      `service` (cada uno con `--config`) y `main(["service"])` sin acción
      lista las siete acciones (`run|status|reload|install|uninstall|start|
      stop`); sin menciones a "Etapa 7" futura en ayuda y docstring.
- [x] `odin service install` sin `--config`/`ODIN_CONFIG` → 2 con mensaje
      claro y sin construir el gestor ni instalar.
- [x] `odin service install` con JSON ilegible/malformado o estructura
      inválida → 2 sin instalar.
- [x] `odin service install` con un hallazgo ERROR de `validate_config`
      (p. ej. `work_dir` que existe como archivo regular) → 2, reporte
      impreso y sin instalar.
- [x] `odin service install` con configuración válida construye el gestor con
      la ruta absoluta del JSON, pasa un `ServiceSpec` con `config_path`
      absoluta (la del JSON) y el ejecutable resuelto, imprime el mensaje del
      gestor + pasos siguientes y devuelve 0.
- [x] `uninstall`/`start`/`stop` construyen el gestor con la fuente
      `--config`/`ODIN_CONFIG` resuelta a absoluta (o un centinela absoluto sin
      fuente), invocan la operación correspondiente, imprimen su mensaje y
      devuelven 0.
- [x] Un fallo operativo del gestor (`ServiceError`, `ServiceUnsupportedError`)
      en cualquier acción → 1 con el motivo en stderr; ninguna acción toca
      `systemctl` ni el SCM real (todo con gestor doble inyectado).
- [x] `_service_executable()` resuelve una ruta absoluta existente cuando
      `sys.argv[0]` la aporta, cae a `shutil.which("odin")` y devuelve `"odin"`
      como último recurso.
- [x] Tests en `tests/test_cli.py`: install sin fuente/config inválida/entorno
      con ERROR → 2 y sin instalar, spec absoluto + pasos siguientes, cada
      acción 0/1 según el gestor, plataforma no soportada → 1, ayuda
      coherente; sin `systemctl`/SCM reales.
- [x] Gates del item en verde: `uv run pytest tests/test_cli.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Registrar en `build_parser` los subparsers `install`, `uninstall`, `start`
   y `stop` con `--config`; actualizar las descripciones y el docstring del
   módulo.
2. Escribir en `cli.py` el alias `ManagerFactory`, los helpers
   `_service_executable` y `_service_manager_config_path` (o equivalente) y los
   handlers `_cmd_service_install` / `_cmd_service_lifecycle`; cablear
   `_cmd_service` y su mensaje de acción requerida.
3. Escribir los tests del item en `tests/test_cli.py` con un gestor doble
   (`odin.cli.create_service_manager` monkeypatcheado) que registra specs y se
   puede hacer fallar por acción.
4. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_cli.py -q` (in-process con `main([...])` y
  `capsys`, patrón existente del módulo).
- Gestor doble: `unittest.mock`/clase mínima que implementa
  `install/uninstall/start/stop/status` y registra el `ServiceSpec` y la ruta
  con la que se construyó; un `error` inyectable por acción lanza
  `ServiceError` para cubrir el exit 1; `ServiceUnsupportedError` cubre la
  plataforma no soportada.
- Configuraciones: `_write_config` (helper local) para el caso válido y las
  mutaciones (JSON malformado, `work_dir` apuntando a un archivo) para los
  exits 2.
- `_service_executable` se cubre por separado con `sys.argv`/`shutil.which`
  monkeypatcheados (ruta existente, fallback, último recurso).
- La ayuda se verifica con `main(["service", "--help"])` bajo
  `pytest.raises(SystemExit)` y `capsys`.
- Gates: ruff y mypy completos.

## Dependencies

- Items 059-061 (`ServiceSpec`/`ServiceManager`/`create_service_manager` y
  gestores Linux/Windows).
- Item 006 (`validate_config`) y `_resolve_config_source`/`_load_config_or_report`
  de la CLI.
- Insumos: `queue-007.md` (Lote B) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **`install` valida el entorno, no solo el JSON**: `load_config` cubre
  estructura/semántica, pero instalar un servicio que fallaría al arrancar
  (p. ej. `work_dir` que existe como archivo) deja un residuo en el gestor del
  SO. Se reutiliza `validate_config` (Item 006) y se aborta con 2 **solo** ante
  hallazgos ERROR; las advertencias (permisos del JSON, `private_key` ausente,
  gbak no encontrado) no bloquean: son avisos legítimos de despliegue que no
  impiden el arranque del scheduler.
- **Resolución del ejecutable en la CLI, no en `ServiceSpec`**: systemd exige
  un `ExecStart` absoluto, mientras que Windows no consume el ejecutable (el
  SCM registra la clase `odin.service.windows.OdinWindowsService`). El default
  `"odin"` del spec se conserva para tests/Windows y la CLI resuelve
  `sys.argv[0]` (lo invocado: `.../.venv/bin/odin` con `uv run`/`uv tool
  install`) con `shutil.which("odin")` de respaldo; si ninguno existe se pasa
  `"odin"` y el gestor Linux reporta el `ServiceError` accionable del render.
- **`uninstall`/`start`/`stop` no cargan el JSON**: identifican el servicio por
  nombre fijo y no consumen la ruta, pero el contrato del gestor exige una
  config absoluta; sin `--config`/`ODIN_CONFIG` se pasa el centinela
  `<cwd>/config.json` (nunca leído por esas operaciones) en lugar de inventar
  una config o exigirla de más.
- **`manager_factory` inyectable + monkeypatch del módulo**: el parámetro sigue
  el patrón de `service_factory` en `_cmd_service_run`; los tests de CLI
  monkeypatchean `odin.cli.create_service_manager` para no tocar
  `systemctl`/SCM y poder registrar la ruta y el `ServiceSpec` reales.
- **Pasos siguientes por plataforma**: el mensaje del gestor ya trae la guía
  exacta sin permisos (Item 060); la CLI agrega una línea con
  `odin service start` y, en Linux, la alternativa `sudo systemctl start
  odin.service`, sin duplicar la unit renderizada.

**Evidencia:** `uv run pytest tests/test_cli.py -q` → **88 passed** (17 casos
nuevos del item: install sin fuente / JSON malformado / ERROR de entorno → 2
sin construir el gestor, spec absoluto + pasos siguientes, error del gestor y
plataforma no soportada → 1, ciclo `uninstall|start|stop` 0 y 1 por acción,
centinela sin config, resolución del ejecutable en sus tres ramas y ayuda con
las siete acciones); `uv run ruff check src/odin tests` → All checks passed;
`uv run mypy src/odin` → Success: no issues found in 18 source files.

## Prerequisites

- No requiere systemd ni Windows: el ciclo completo se cubre con el gestor
  doble; la verificación con la CLI real y `systemctl` doble llega en el Item
  066.
- `docs/aide/progress.md` debe reflejar el avance del entregable CLI al
  completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.
