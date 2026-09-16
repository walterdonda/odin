# ODIN — Modo servicio residente

ODIN puede correr desatendido como **servicio del sistema operativo**: un
Windows Service (gestionado por el SCM) en Windows Server y una unit
**systemd** en Linux LTS. El servicio ejecuta el **scheduler interno** del
bloque `scheduler` del JSON: cada job dispara el pipeline completo (respaldo
`gbak`, compresión 7z, transferencia SFTP, correo y retención local) según su
expresión cron, **sin depender de `cron`, timers de systemd ni Task
Scheduler**.

- Comandos del ciclo de vida:
  `odin service install|uninstall|start|stop|status`.
- `odin service run` es el mismo runtime en primer plano que usa el servicio
  (`src/odin/service/runner.py`): sirve para probar y depurar.
- `odin service reload` pide la recarga de la configuración sin reiniciar.
- El estado consultable vive en `local.work_dir/scheduler_state.json` y el log
  en `<resolved_log_dir>/odin.log` (ver [Logging](#6-logging)).

---

## 1. Antes de instalar

1. **Configuración válida y absoluta.** El servicio corre desatendido: no tiene
   cwd de shell ni `ODIN_CONFIG`. `odin service install` resuelve la ruta del
   JSON a absoluta, la carga y la valida; un ERROR de estructura o de entorno
   aborta la instalación con exit code 2 (no se instala un servicio con una
   configuración que fallaría al arrancar). Antes de instalar:

   ```bash
   odin validate --config /etc/odin/config.json
   ```

2. **Scheduler habilitado con al menos un job.** `odin service run` exige
   `scheduler.enabled: true`; con `false` devuelve 2 y el servicio queda
   arrancando y muriendo.

3. **Visibilidad para la cuenta del servicio.** La cuenta que corra el servicio
   debe poder:
   - **leer** el JSON de configuración (permisos `600`/ACL del dueño),
   - **crear y escribir** `local.work_dir` y el directorio de logs,
   - **ejecutar** `gbak` (o el binario indicado en `databases[].gbak_path`),
   - alcanzar por red el servidor Firebird (3050/TCP o el puerto configurado),
     los servidores SFTP (22/TCP) y el servidor SMTP.

   El detalle de permisos, claves SSH, políticas de host key y mínimo
   privilegio está en la guía de seguridad:
   [`docs/security.md`](security.md).

4. **Permisos de instalación.** En Linux hace falta `root` (o un usuario con
   permiso de escritura sobre `/etc/systemd/system`); en Windows, una consola
   **elevada** (Administrador). Sin permisos, ODIN no falla: imprime la guía
   exacta para completar la instalación a mano (solo en Linux; ver §3.1).

5. **El ejecutable `odin`.** El servicio arranca el scheduler en modo residente
   (`odin service run --config <ruta>`); instalalo con `uv tool install`
   (Etapa 8) o desde el entorno de desarrollo. En Linux el `ExecStart` debe ser
   una **ruta absoluta**: si `sys.argv[0]` no es resoluble, el gestor rechaza
   la unit con un mensaje accionable.

---

## 2. Ciclo de vida

| Comando | Efecto | Exit 0 | Exit ≠ 0 |
|---|---|---|---|
| `odin service install --config <ruta>` | Instala (o reemplaza) el servicio, con arranque automático y reinicio ante caída | Mensaje de instalación (o guía sin permisos en Linux) | 2: falta la config o es inválida · 1: fallo del gestor |
| `odin service uninstall` | Detiene, deshabilita y elimina el servicio (idempotente) | Desinstalado o "no estaba instalado" | 1: fallo del gestor |
| `odin service start` | Arranca el servicio y espera su transición a "en ejecución" | Arrancado (o "ya estaba en ejecución") | 1: fallo del gestor |
| `odin service stop` | Detiene el servicio y espera su transición a "detenido" | Detenido (o "ya estaba detenido") | 1: fallo del gestor |
| `odin service status` | Consulta el estado del gestor y del scheduler | Estado impreso (incluye "no instalado" y estado ausente) | 2: no se pudo cargar la config |
| `odin service reload` | Pide la recarga en caliente de la configuración | Solicitud entregada | 1: no hay servicio en ejecución · 2: config ilegible |

`uninstall`, `start` y `stop` operan por **nombre fijo `odin`**; `--config` es
opcional en ellos (solo se usa para construir el gestor). Comprobar el estado
con `odin service status` es siempre la primera acción de diagnóstico.

---

## 3. Linux (systemd)

### 3.1 Instalación

```bash
sudo odin service install --config /etc/odin/config.json
```

- **Con permisos** (root o usuario con escritura en `/etc/systemd/system`):
  escribe la unit `odin.service`, ejecuta `systemctl daemon-reload` y, con
  `auto_start`, `systemctl enable odin.service`. La instalación **no arranca**
  el servicio: el paso siguiente es `odin service start` (o
  `sudo systemctl start odin.service`).
- **Sin permisos**: no escribe nada y devuelve la guía con la unit renderizada
  y los comandos `sudo` a ejecutar. Copiá el contenido a
  `/etc/systemd/system/odin.service` y luego:

  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable odin.service   # arranque en boot (si auto_start)
  sudo systemctl start odin.service
  ```

`deploy/odin.service` versiona la **unit de referencia** con la misma
estructura —`[Unit]` (`Description`, `After`/`Wants=network-online.target`),
`[Service]` (`Type=simple`, `ExecStart=<odin absoluto> service run --config
<ruta absoluta>`, `WorkingDirectory`, `Restart=always`, `RestartSec=5`,
`User=`/`Group=` opcionales) y `[Install]` (`WantedBy=multi-user.target`)— y
placeholders documentados para el ejecutable (`/opt/odin/bin/odin`) y la
config (`/etc/odin/config.json`). `odin service install` genera esa misma unit
con las rutas reales del host.

### 3.2 Cuenta del servicio: root vs usuario dedicado

Por defecto la unit no declara `User=`, así que corre como **root** (el
`sudo` de la instalación). Para producción se recomienda una cuenta dedicada:

```ini
[Service]
User=odin
Group=odin
```

- La CLI **no expone** el flag de cuenta: `odin service install` siempre
  instala con la cuenta por defecto de la plataforma (root). Para una cuenta
  dedicada, editá la unit generada (o `deploy/odin.service`) y volvé a
  `daemon-reload` + `start`. El contrato `ServiceSpec.account`
  (`usuario` o `usuario:grupo`) soporta esto para uso programático.
- Creá el usuario sin login (`useradd --system --home /var/lib/odin --shell
  /usr/sbin/nologin odin`) y dale lectura al JSON y escritura a `work_dir` y
  al directorio de logs. El JSON con secretos en texto legible debe quedar
  `chown odin` y permisos `600`; `odin validate` advierte si tiene acceso de
  grupo/otros. Procedimiento completo y checklist:
  [`docs/security.md`](security.md).

### 3.3 Arranque en boot y reinicio ante caída

- `systemctl enable odin.service` (o `enable --now`) lo activa en el arranque:
  `WantedBy=multi-user.target` + `Restart=always`.
- `Restart=always` + `RestartSec=<restart_delay_seconds>` (default 5 s)
  reinician el proceso si se cae, se lo mata o termina de forma anómala. El
  scheduler interno sobrevive a los fallos de cada ciclo; este reinicio cubre
  caídas del proceso.
- Comprobación: `systemctl is-enabled odin.service` y
  `systemctl is-active odin.service`.

### 3.4 Recarga en caliente

Editá el JSON y pedí la recarga sin reiniciar:

```bash
sudo odin service reload --config /etc/odin/config.json
# o directamente:
sudo systemctl kill -s SIGUSR1 odin.service
```

La CLI envía `SIGUSR1` al `pid` del estado; el servicio lo captura como una
bandera thread-safe y el job interno `reload-watcher` (cada 2 s) la procesa:
vuelve a cargar y validar la configuración, aplica timezone/jobs/próximos
disparos y reconfigura el logging, todo sin detener el scheduler. Si la config
nueva es inválida, **conserva la vigente** y registra el motivo en el log y en
`recent_errors`. Si la señal no llega (p. ej. servicio caído), `reload`
devuelve 1. El archivo de control `local.work_dir/scheduler_reload.request`
funciona como vía alternativa (lo consume el mismo watcher).

### 3.5 Desinstalación limpia

```bash
sudo odin service uninstall
```

Detiene, deshabilita y borra la unit, y ejecuta `daemon-reload` solo si había
algo que desinstalar. Es idempotente: una segunda invocación informa que no
estaba instalado. Los respaldos, logs y el JSON **no se tocan**.

---

## 4. Windows Server

### 4.1 Instalación

Desde una consola **elevada** (Administrador):

```powershell
odin service install --config C:\odin\config.json
odin service start
odin service status
```

- `install` registra el servicio en el SCM con arranque **automático**
  (`SERVICE_AUTO_START`) y, por defecto, **reinicio ante caída**: failure
  actions del SCM que reinician el proceso `restart_delay_seconds` (default
  5 s) después de un fallo, con reset periódico (24 h). La clase del servicio
  se registra como `odin.service.windows.OdinWindowsService` y la corre el
  host de servicios de pywin32 (`pywin32` se instala solo en Windows por el
  marker del paquete).
- La ruta **absoluta** del JSON y la de trabajo quedan fijadas en la
  instalación como opciones del servicio: el arranque no depende de variables
  de entorno ni del cwd.
- La instalación **no arranca** el servicio: usá `odin service start` (el
  arranque automático aplica en el próximo boot). `uninstall|start|stop`
  operan por nombre fijo `odin`.

### 4.2 Cuenta de servicio y accesos

Por defecto el SCM instala el servicio con la cuenta **LocalSystem**, que
tiene acceso local amplio y salida de red. Si se usa una cuenta dedicada
(`ServiceSpec.account`, o `sc.exe config odin obj= DOMINIO\cuenta
password= ...`), esa cuenta necesita:

- lectura del JSON de configuración,
- escritura en `local.work_dir` y en el directorio de logs,
- ejecución de `gbak` (p. ej. `C:\Program Files\Firebird\Firebird_5_0\bin`),
- acceso de red al Firebird, a los SFTP y al SMTP configurados.

La CLI no expone el flag de cuenta: `odin service install` instala con la
cuenta por defecto. Para una cuenta dedicada, ajustá el servicio con las
herramientas del SCM o usá `ServiceSpec.account` programáticamente. El mínimo
privilegio y las ACL del JSON se detallan en [`docs/security.md`](security.md).

### 4.3 Actualización de la configuración y recarga

1. Editá el JSON en la ruta fijada en la instalación.
2. Pedí la recarga sin reiniciar:

   ```powershell
   odin service reload --config C:\odin\config.json
   ```

En Windows no hay `SIGUSR1`: la CLI crea el archivo de control
`local.work_dir\scheduler_reload.request` (por eso conviene pasar la **misma**
config que usa el servicio) y el `reload-watcher` lo consume en ≤ 2 s. La
config nueva se valida antes de aplicarse; si es inválida, el servicio
mantiene la vigente y el motivo queda en `odin.log` y en `recent_errors`. Un
cambio que el watcher no pueda cubrir (p. ej. rutas de log) se aplica reiniciando:
`odin service stop` + `odin service start`.

### 4.4 Registro del SCM y eventos

- Estado del servicio: `services.msc`, `sc query odin` o
  `Get-Service odin`. El SCM reporta arranque/detención/pendiente y, con las
  failure actions, los reinicios.
- `odin service status` muestra ese estado junto con el del scheduler.
- El host de servicios de pywin32 registra los errores del arranque
  (`SvcDoRun`/`SvcStop`) en el **Visor de eventos** (registro de
  Aplicación) mediante `servicemanager`. La primera fuente de diagnóstico
  sigue siendo `odin.log`.

### 4.5 Desinstalación limpia

```powershell
odin service uninstall
```

Detiene y elimina el servicio con el SCM; es idempotente. La configuración,
los respaldos y los logs no se tocan.

---

## 5. Lectura de `odin service status`

El comando compone dos bloques: el **servicio del SO** (gestor `systemd` o
`windows`: instalado, en ejecución, arranque automático, política de reinicio
y detalle del gestor) y el **scheduler** (`scheduler_state.json`: cada job con
próximo disparo y último ciclo, salud y errores recientes). Es una consulta de
solo lectura: devuelve 0 mientras la configuración cargue y el estado se pueda
interpretar, incluso si el gestor falla (en ese caso imprime una advertencia).

```text
Servicio del SO (systemd): no instalado.
Sugerencia: instale el servicio residente con 'odin service install --config <ruta>'.

Scheduler:
Servicio ODIN: sin estado
Ruta: /var/backups/odin/scheduler_state.json
Motivo: no existe el archivo de estado: /var/backups/odin/scheduler_state.json
```

```text
Servicio del SO (systemd): en ejecución.
  Arranque automático: sí
  Reinicio ante caída: sí
  Detalle: LoadState=loaded, ActiveState=active, UnitFileState=enabled, Restart=always

Scheduler:
Servicio ODIN: en ejecución (pid 12345)
Config: /etc/odin/config.json
Iniciado: 2026-09-15T02:00:03+00:00
Última actualización: 2026-09-15T02:00:15+00:00
Salud: OK
Jobs (1):
- job-1 [erp_principal] schedule '0 2 * * *'
  Próximo disparo: 2026-09-16T02:00:00+00:00
  Último ciclo: success en 8.4 s (erp_principal; correo enviado)
```

Estados posibles y sugerencias:

| Situación | Salida |
|---|---|
| Servicio no instalado | Sugiere `odin service install` |
| Instalado y detenido | Sugiere `odin service start` |
| Corriendo con estado vigente | `pid` vivo, jobs, próximo disparo y salud |
| Corriendo con estado obsoleto | El `pid` del estado ya no vive: lo reporta como **detenido** (estado obsoleto) |
| Sin `scheduler_state.json` | "sin estado"; el servicio puede estar arrancando |
| Gestor inaccesible (`systemctl`/SCM caído) | Advertencia y sección del scheduler igual |

---

## 6. Logging

| Aspecto | Valor |
|---|---|
| Archivo | `<resolved_log_dir>/odin.log` (`local.log_dir` o, si falta, `<local.work_dir>/logs`) |
| Rotación | 5 MiB por archivo × 5 backups (`odin.log.1` … `odin.log.5`) |
| Modo residente | **Solo archivo**: sin `StreamHandler` (bajo systemd/SCM no hay consola) |
| `stdout`/`stderr` | Redirigidos al mismo log durante la corrida; un `print` perdido no tumba el proceso |
| Nivel | `local.log_level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| Secretos | Contraseñas y claves privadas enmascaradas (`***`) antes de escribir |

`odin service run` en primer plano conserva la consola (útil para probar). El
directorio de logs se crea si no existe; si el destino no es escribible, el
proceso arranca igual con una advertencia y los `print` se descartan.

---

## 7. Diagnóstico de fallos comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| El servicio arranca y muere en Linux | `ExecStart` no absoluto, binario inexistente o unit sin `daemon-reload` | `systemctl status odin` + `journalctl -u odin`; corregir la unit, `daemon-reload`, `start` |
| `odin service run` devuelve 2 y no arranca | `scheduler.enabled: false` o config inválida | Habilitar el scheduler / corregir la config (`odin validate`) y recargar o reiniciar |
| El servicio no encuentra la configuración | Unit escrita a mano con ruta relativa, o JSON movido después de instalar | Usar rutas **absolutas**; reinstalar con `odin service install --config <ruta absoluta>` |
| `Permission denied` al crear `work_dir`/logs, o JSON ilegible | La cuenta del servicio no tiene permisos sobre esas rutas | Ajustar dueño/permisos (`chown`/ACL) al usuario que corre el servicio |
| Ciclos con error de `gbak` | Cuenta sin acceso al binario, a la base Firebird o a la red (puerto 3050/firewall) | Probar `odin run --config ...` con esa cuenta; corregir `gbak_path`, permisos o firewall |
| Los jobs disparan a la hora equivocada | `scheduler.timezone` distinta de la esperada | Ajustar la zona IANA; `odin validate` muestra el próximo disparo por job |
| No llegan los correos / falla SFTP | Salida SMTP/SFTP bloqueada por firewall/proxy | Probar con `odin run`; abrir los puertos de `notification.smtp` y `servers[].host/port` |
| `systemctl` rechaza la unit | Sintaxis inválida o `ExecStart`/`WorkingDirectory` inexistentes | `systemd-analyze verify /etc/systemd/system/odin.service` |
| Windows: el servicio no arranca | Config fijada en la instalación ilegible para la cuenta, o error del host pywin32 | Visor de eventos (Aplicación) + `odin.log`; reinstalar con la cuenta/ruta correctas |
| `odin service status` dice "detenido" con pid muerto | El proceso se cayó y el gestor no lo relanzó (o se detuvo a mano) | Revisar `odin.log`; `odin service start`; confirmar `Restart=always`/failure actions |

---

## 8. Runbook de verificación en Windows Server real

La suite automatizada cubre el ciclo de vida de Windows con dobles de
`win32serviceutil`/`win32service` (no hay Windows real en desarrollo). El
arranque en boot y la recuperación ante caída se verifican con este runbook en
un **Windows Server real** (Etapa 8 / Item 074; ver §9 para la evidencia):

1. `odin validate --config C:\odin\config.json` → sin errores.
2. `odin service install --config C:\odin\config.json` (consola elevada).
3. `odin service start` → `odin service status` informa "en ejecución".
4. **Reiniciar el SO** y, sin tocar nada, confirmar que el servicio volvió a
   arrancar solo (`Get-Service odin` = `Running`) y que el scheduler disparó
   según el horario (un ciclo en `odin.log` y el correo correspondiente).
5. Matar el proceso del servicio (Task Manager o
   `Stop-Process -Id <pid> -Force`): el SCM debe reiniciarlo solo a los
   ~5 s (failure actions) y el siguiente ciclo debe correr.
6. `odin service status` → servicio en ejecución + último ciclo del scheduler.
7. `odin service uninstall` → servicio eliminado; repetir la desinstalación
   para comprobar que es idempotente.

El equivalente Linux (sobrevivir un reinicio del SO) se verifica análogamente
con `systemctl reboot` y `systemctl is-enabled odin`; la variante automatizada
del reinicio ante caída es la demo gated `ODIN_SERVICE_DEMO=1` de
`tests/test_service_linux_integration.py`. La evidencia de las corridas
(automática en CI y manual por runbook) se registra en §9.

---

## 9. Evidencia de verificación (Item 074)

Estado de la **verificación en limpio en Windows Server** y cierre del
**Item 009** (smoke multiplataforma). En este entorno de desarrollo solo hay
Linux: no hay Windows Server ni remoto publicado, así que la corrida real
queda **delegada** al job `windows` de la CI (`.github/workflows/ci.yml`,
Item 073) o al runbook de §8, con el mismo criterio de salvedades que las
Etapas 5 y 7.

### 9.1 Ejecutado (Linux, 2026-09-15)

| Verificación | Comando | Resultado |
|---|---|---|
| Gestor Windows con dobles de pywin32 | `uv run pytest tests/test_service_windows.py -q` | 31 passed |
| Escenario real del SCM: recolección y salto seguro | `uv run pytest tests/test_service_windows_integration.py -q` | 1 skipped (solo Windows) |
| Contrato del workflow de CI | `uv run pytest tests/test_ci_workflow.py -q` | 6 passed |
| Gate único del proyecto | `uv run python scripts/verify.py` | EXIT 0 (6 pasos) |

Detalles de la preparación:

- **Escenario gated del servicio Windows**
  (`tests/test_service_windows_integration.py`, Item 073): con
  `ODIN_WINDOWS_SERVICE_SMOKE=1` en un Windows real recorre
  `odin service install → start → status → stop → uninstall` contra el SCM,
  con una configuración de scheduler y **fases externas dobles** (`gbak`
  *stub*, `servers: []` y SMTP local del catcher in-process), y afirma un
  correo `[ODIN] ÉXITO`, el `scheduler_state.json` con el último ciclo y el
  estado del SCM (en ejecución, arranque automático, reinicio ante caída).
  Fuera de Windows o sin la variable se salta con motivo: no altera la suite
  local.
- **CI**: el job `linux` y el job `windows` corren el gate único del Item 071
  y publican el wheel; el job `windows` exporta `ODIN_WINDOWS_SERVICE_SMOKE=1`
  para el escenario anterior. El workflow se activa al publicar el
  repositorio, usa `permissions: contents: read` y no consume secretos.
- **Host del servicio**: se revisó el wheel de pywin32 312
  (`LocatePythonServiceExe` copia `pythonservice.exe` al prefijo del entorno y
  `pywintypesNNN.dll` junto a la DLL de Python), de modo que `odin service
  install` desde el entorno de `uv sync` no requiere `pywin32_postinstall`.

### 9.2 Delegado: corrida real en Windows Server

Vía A (recomendada): publicar el repositorio y dejar correr el job `windows`
de la CI (gate completo + smoke del SCM). Vía B: ejecutar el runbook de §8 en
un Windows Server real. La primera corrida debe completar esta evidencia:

| Dato | Valor |
|---|---|
| Fecha / build del SO | _pendiente_ |
| Versiones de `uv` y Python | _pendiente_ |
| Firebird usado (real o fases dobles) | _pendiente_ |
| `odin validate` (exit code) | _pendiente_ |
| `install`/`start`/`status`/`stop`/`uninstall` (salidas y exit codes) | _pendiente_ |
| Estado del SCM: `Get-Service odin`, arranque automático y failure actions | _pendiente_ |
| Ciclo del scheduler y correo del informe | _pendiente_ |
| Reinicio del SO: el servicio vuelve solo | _pendiente_ |
| Caída del proceso: el SCM reinicia (failure actions) | _pendiente_ |
| `uv tool install` desde el wheel en entorno limpio (sin el repo) | _pendiente_ |

> **Salvedad:** el **Item 009** se cierra con la evidencia de Linux
> (Items 071-072: gate `scripts/verify.py` y empaquetado limpio) y la corrida
> real de Windows **delegada** al job `windows` de la CI (Item 073) o al
> runbook §8; no se declara verificada una ejecución en Windows Server que no
> ocurrió en este entorno. Esa corrida es la que aporta la confirmación
> runtime de `pywin32`/Python 3.14 en Windows.

---

## 10. Referencias

- `README.md` — instalación, configuración, `odin run`, notificación,
  retención, scheduler, exit codes.
- `deploy/odin.service` — unit de referencia de systemd.
- `src/odin/service/` — contrato (`base.py`), gestores (`linux.py`,
  `windows.py`) y runtime compartido (`runner.py`).
- Tests: `tests/test_service_*.py` (base, Linux, Windows, status, runner e
  integración de la unit).
