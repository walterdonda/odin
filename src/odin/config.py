"""Modelos de configuración y parseo del JSON de ODIN (Item 002).

Contrato de configuración según visión §5, extendido con campos opcionales de
confiabilidad/observabilidad (timeouts de gbak, umbral de disco libre,
reintentos SFTP, nivel de log y cola de log para el correo a DevOps).

Características:
- Solo stdlib (json, dataclasses, pathlib, enum, zoneinfo, difflib, re) más
  APScheduler (``CronTrigger.from_crontab``, Item 049) para validar las
  expresiones cron con exactamente el mismo parser que usará el scheduler.
- Validación con reporte agregado: todos los problemas de una vez, cada uno
  con ruta de campo (``field_path``) y mensaje legible.
- Campos desconocidos son error, con sugerencia del campo más cercano.
- Normalización completa de rutas locales (``odin.paths``, Item 003):
  separadores ``/`` y ``\\``, expansión de ``~`` y resolución de rutas
  relativas contra el directorio del archivo JSON.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from odin.paths import normalize_path

__all__ = [
    "AuthMethod",
    "CompressionConfig",
    "Config",
    "ConfigError",
    "ConfigProblem",
    "DatabaseConfig",
    "DbEngine",
    "HostKeyPolicy",
    "LocalConfig",
    "LogLevel",
    "MisfirePolicy",
    "NotificationConfig",
    "SchedulerConfig",
    "SchedulerJob",
    "ServerAuth",
    "ServerConfig",
    "SmtpConfig",
    "load_config",
]

_ROOT = "config"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E = TypeVar("_E", bound=Enum)


class LogLevel(Enum):
    """Nivel de logging configurable (``local.log_level``)."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class AuthMethod(Enum):
    """Método de autenticación SFTP (``servers[].auth.method``)."""

    PASSWORD = "password"
    KEY = "key"


class DbEngine(Enum):
    """Motor de la base de datos (``databases[].type``).

    Obligatorio y explícito en cada entrada, sin default: define qué campos
    aplican (Firebird vs. PostgreSQL) y qué motor ejecuta el respaldo.
    """

    FIREBIRD = "firebird"
    POSTGRESQL = "postgresql"


class HostKeyPolicy(Enum):
    """Política de host keys SSH (``servers[].host_key_policy``)."""

    STRICT = "strict"
    KNOWN_HOSTS = "known_hosts"
    ACCEPT_NEW = "accept-new"
    INSECURE = "insecure"


class MisfirePolicy(Enum):
    """Política ante disparos perdidos del scheduler (``jobs[].on_misfire``)."""

    RUN_ONCE = "run_once"
    SKIP = "skip"


@dataclass(frozen=True, kw_only=True, slots=True)
class ConfigProblem:
    """Problema individual de validación: ruta del campo y mensaje legible."""

    field_path: str
    message: str


class ConfigError(Exception):
    """Error de configuración con el reporte agregado de todos los problemas."""

    def __init__(self, problems: Sequence[ConfigProblem]) -> None:
        self.problems: list[ConfigProblem] = list(problems)
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"{len(self.problems)} problema(s) de configuración:"]
        lines.extend(f"- {p.field_path}: {p.message}" for p in self.problems)
        return "\n".join(lines)


@dataclass(frozen=True, kw_only=True, slots=True)
class DatabaseConfig:
    """Base de datos a respaldar, Firebird o PostgreSQL según ``type``.

    ``type`` es obligatorio y sin default. Los campos con nombre de motor solo
    aplican a su motor (la exigencia/el rechazo por motor es semántico, en
    ``Config.validate_semantics``): ``connection``/``role``/``charset``/
    ``gbak_path``/``gbak_timeout_sec`` para Firebird; ``host``/``port``/
    ``dbname``/``pg_dump_path``/``pg_dump_timeout_sec`` para PostgreSQL.
    ``port`` es ``None`` cuando está ausente (presencia explícita detectable);
    el default efectivo 5432 lo aplica el engine al construir el comando.
    """

    name: str
    type: DbEngine
    user: str
    password: str
    connection: str | None = None
    role: str | None = None
    charset: str | None = None
    gbak_path: str | None = None
    gbak_timeout_sec: int | None = None
    host: str | None = None
    port: int | None = None
    dbname: str | None = None
    pg_dump_path: str | None = None
    pg_dump_timeout_sec: int | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ServerAuth:
    """Autenticación de un servidor SFTP."""

    method: AuthMethod
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ServerConfig:
    """Servidor SFFTP destino de las copias."""

    name: str
    host: str
    port: int
    username: str
    auth: ServerAuth
    remote_path: str
    host_key_policy: HostKeyPolicy = HostKeyPolicy.STRICT
    sftp_retries: int = 3
    sftp_connect_timeout_sec: int = 30
    sftp_operation_timeout_sec: int = 60
    sftp_retry_backoff_base: float = 2.0
    sftp_retry_max_delay_sec: float = 30.0


@dataclass(frozen=True, kw_only=True, slots=True)
class SmtpConfig:
    """Servidor SMTP para la notificación por correo.

    ``starttls`` (default) y ``ssl`` son mutuamente excluyentes: ``ssl`` usa
    SSL implícito (típicamente puerto 465) y exige ``starttls: false``.
    """

    host: str
    port: int
    starttls: bool = True
    ssl: bool = False
    username: str = ""
    password: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class NotificationConfig:
    """Destinatarios y servidor de correo (``from_`` mapea el JSON ``from``)."""

    to: str
    from_: str
    smtp: SmtpConfig
    log_tail_lines: int = 50


@dataclass(frozen=True, kw_only=True, slots=True)
class CompressionConfig:
    """Compresión 7z de los respaldos."""

    level: int = 7
    password: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class LocalConfig:
    """Directorios, retención y parámetros operativos locales."""

    work_dir: Path
    retention_days: int
    log_level: LogLevel = LogLevel.INFO
    log_dir: Path | None = None
    min_free_mb: int = 1024
    gbak_timeout_sec: int = 7200
    pg_dump_timeout_sec: int = 7200
    sftp_retries: int = 3
    sftp_connect_timeout_sec: int = 30

    @property
    def resolved_log_dir(self) -> Path:
        """Directorio de logs efectivo: ``log_dir`` o ``<work_dir>/logs``."""
        return self.log_dir if self.log_dir is not None else self.work_dir / "logs"


@dataclass(frozen=True, kw_only=True, slots=True)
class SchedulerJob:
    """Job del scheduler: bases a respaldar y horario tipo cron."""

    databases: list[str]
    schedule: str
    on_misfire: MisfirePolicy = MisfirePolicy.RUN_ONCE
    skip_if_running: bool = True


@dataclass(frozen=True, kw_only=True, slots=True)
class SchedulerConfig:
    """Scheduler interno (deshabilitado por defecto)."""

    enabled: bool = False
    timezone: str = "UTC"
    jobs: list[SchedulerJob] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True, slots=True)
class Config:
    """Configuración completa, validada e inmutable de ODIN."""

    databases: list[DatabaseConfig]
    compression: CompressionConfig
    servers: list[ServerConfig]
    notification: NotificationConfig
    local: LocalConfig
    scheduler: SchedulerConfig
    config_path: Path

    def validate_semantics(self) -> list[ConfigProblem]:
        """Validaciones cruzadas sobre el modelo ya construido.

        Cubre unicidad de nombres, referencias de los jobs del scheduler,
        coherencia entre ``auth.method`` y los campos de credenciales, y las
        reglas por motor de ``databases[].type`` (``_db_problems``).
        """
        problems: list[ConfigProblem] = []
        problems.extend(
            _duplicate_problems([db.name for db in self.databases], f"{_ROOT}.databases")
        )
        problems.extend(
            _duplicate_problems([server.name for server in self.servers], f"{_ROOT}.servers")
        )
        known_databases = {db.name for db in self.databases}
        for job_index, job in enumerate(self.scheduler.jobs):
            for db_index, name in enumerate(job.databases):
                if name not in known_databases:
                    problems.append(
                        ConfigProblem(
                            field_path=f"{_ROOT}.scheduler.jobs[{job_index}].databases[{db_index}]",
                            message=f"referencia una base de datos inexistente: '{name}'",
                        )
                    )
        for index, database in enumerate(self.databases):
            problems.extend(_db_problems(database, f"{_ROOT}.databases[{index}]"))
        for index, server in enumerate(self.servers):
            problems.extend(_auth_problems(server.auth, f"{_ROOT}.servers[{index}].auth"))
        return problems

    def iter_secret_fields(self) -> Iterator[tuple[str, str]]:
        """Yield-ea ``(field_path, valor)`` de los campos sensibles presentes.

        Insumo para el enmascarado de secretos (Item 004) y los correos de
        ejecución (Etapa 5).
        """
        for index, database in enumerate(self.databases):
            yield f"{_ROOT}.databases[{index}].password", database.password
        if self.compression.password is not None:
            yield f"{_ROOT}.compression.password", self.compression.password
        for index, server in enumerate(self.servers):
            auth = server.auth
            if auth.password is not None:
                yield f"{_ROOT}.servers[{index}].auth.password", auth.password
            if auth.private_key is not None:
                yield f"{_ROOT}.servers[{index}].auth.private_key", auth.private_key
            if auth.passphrase is not None:
                yield f"{_ROOT}.servers[{index}].auth.passphrase", auth.passphrase
        yield f"{_ROOT}.notification.smtp.password", self.notification.smtp.password


def _duplicate_problems(names: Sequence[str], section_path: str) -> list[ConfigProblem]:
    problems: list[ConfigProblem] = []
    first_index: dict[str, int] = {}
    for index, name in enumerate(names):
        if name in first_index:
            problems.append(
                ConfigProblem(
                    field_path=f"{section_path}[{index}].name",
                    message=(
                        f"nombre duplicado '{name}' "
                        f"(ya usado en {section_path}[{first_index[name]}].name)"
                    ),
                )
            )
        else:
            first_index[name] = index
    return problems


def _auth_problems(auth: ServerAuth, path: str) -> list[ConfigProblem]:
    problems: list[ConfigProblem] = []
    if auth.method is AuthMethod.PASSWORD:
        if not auth.password:
            problems.append(
                ConfigProblem(
                    field_path=f"{path}.password",
                    message="es requerido cuando auth.method es 'password'",
                )
            )
        if auth.private_key is not None:
            problems.append(
                ConfigProblem(
                    field_path=f"{path}.private_key",
                    message="solo aplica cuando auth.method es 'key'",
                )
            )
        if auth.passphrase is not None:
            problems.append(
                ConfigProblem(
                    field_path=f"{path}.passphrase",
                    message="solo aplica cuando auth.method es 'key'",
                )
            )
    else:
        if not auth.private_key:
            problems.append(
                ConfigProblem(
                    field_path=f"{path}.private_key",
                    message="es requerido cuando auth.method es 'key'",
                )
            )
        if auth.password is not None:
            problems.append(
                ConfigProblem(
                    field_path=f"{path}.password",
                    message="solo aplica cuando auth.method es 'password'",
                )
            )
    return problems


_FIREBIRD_ONLY_FIELDS = ("connection", "role", "charset", "gbak_path", "gbak_timeout_sec")
_POSTGRESQL_ONLY_FIELDS = ("host", "port", "dbname", "pg_dump_path", "pg_dump_timeout_sec")

# Reglas por motor: (motor, campos_requeridos, campos_ajenos, otro_motor).
# ``campos_requeridos`` son los de conexión exigidos por el motor; los
# ``campos_ajenos`` (del otro motor) presentes disparan "solo aplica…".
_DB_ENGINE_RULES: tuple[tuple[DbEngine, tuple[str, ...], tuple[str, ...], DbEngine], ...] = (
    (DbEngine.FIREBIRD, ("connection",), _POSTGRESQL_ONLY_FIELDS, DbEngine.POSTGRESQL),
    (DbEngine.POSTGRESQL, ("host", "dbname"), _FIREBIRD_ONLY_FIELDS, DbEngine.FIREBIRD),
)


def _db_problems(database: DatabaseConfig, path: str) -> list[ConfigProblem]:
    """Reglas por motor de ``databases[]`` (espejo del patrón ``_auth_problems``).

    El parse estructural valida solo tipos de dato; la exigencia y el rechazo
    de campos según ``type`` es semántico: un campo de un motor presente en una
    entrada del otro es problema ("solo aplica cuando type es '<motor>'"), y
    el campo de conexión requerido por el motor ausente también ("es requerido
    cuando type es '<motor>'"). ``null`` cuenta como ausente.
    """
    problems: list[ConfigProblem] = []
    for motor, required_fields, foreign_fields, other_motor in _DB_ENGINE_RULES:
        if database.type is not motor:
            continue
        for field_name in required_fields:
            if not getattr(database, field_name):
                problems.append(
                    ConfigProblem(
                        field_path=f"{path}.{field_name}",
                        message=f"es requerido cuando type es '{motor.value}'",
                    )
                )
        for field_name in foreign_fields:
            if getattr(database, field_name) is not None:
                problems.append(
                    ConfigProblem(
                        field_path=f"{path}.{field_name}",
                        message=f"solo aplica cuando type es '{other_motor.value}'",
                    )
                )
        break
    return problems


@dataclass(slots=True)
class _Validator:
    """Acumula problemas de validación estructural sin fallar en cascada."""

    problems: list[ConfigProblem] = field(default_factory=list)

    def add(self, path: str, message: str) -> None:
        self.problems.append(ConfigProblem(field_path=path, message=message))

    def mapping(self, value: Any, path: str) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        self.add(path, f"debe ser un objeto JSON, se encontró {type(value).__name__}")
        return None

    def list_field(self, value: Any, path: str) -> list[Any] | None:
        if isinstance(value, list):
            return value
        self.add(path, f"debe ser una lista JSON, se encontró {type(value).__name__}")
        return None

    def str_field(
        self,
        raw: dict[str, Any],
        key: str,
        path: str,
        *,
        required: bool = True,
        nullable: bool = False,
        default: str | None = None,
    ) -> str | None:
        field_path = f"{path}.{key}"
        if key not in raw:
            if required:
                self.add(field_path, "campo requerido ausente")
            return default
        value = raw[key]
        if value is None:
            if nullable:
                return None
            self.add(field_path, "no debe ser null")
            return default
        if not isinstance(value, str):
            self.add(
                field_path, f"debe ser una cadena de texto, se encontró {type(value).__name__}"
            )
            return default
        if not value.strip():
            self.add(field_path, "no debe ser una cadena vacía")
            return default
        return value

    def int_field(
        self,
        raw: dict[str, Any],
        key: str,
        path: str,
        *,
        required: bool = True,
        nullable: bool = False,
        default: int | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
        exclusive_minimum: int | None = None,
    ) -> int | None:
        field_path = f"{path}.{key}"
        if key not in raw:
            if required:
                self.add(field_path, "campo requerido ausente")
            return default
        value = raw[key]
        if value is None:
            if nullable:
                return None
            self.add(field_path, "no debe ser null")
            return default
        if not isinstance(value, int) or isinstance(value, bool):
            self.add(field_path, f"debe ser un entero, se encontró {type(value).__name__}")
            return default
        if minimum is not None and value < minimum:
            self.add(field_path, f"debe ser un entero >= {minimum}, se encontró {value}")
            return default
        if exclusive_minimum is not None and value <= exclusive_minimum:
            self.add(field_path, f"debe ser un entero > {exclusive_minimum}, se encontró {value}")
            return default
        if maximum is not None and value > maximum:
            self.add(field_path, f"debe ser un entero <= {maximum}, se encontró {value}")
            return default
        return value

    def float_field(
        self,
        raw: dict[str, Any],
        key: str,
        path: str,
        *,
        required: bool = True,
        nullable: bool = False,
        default: float | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        field_path = f"{path}.{key}"
        if key not in raw:
            if required:
                self.add(field_path, "campo requerido ausente")
            return default
        value = raw[key]
        if value is None:
            if nullable:
                return None
            self.add(field_path, "no debe ser null")
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.add(field_path, f"debe ser un número, se encontró {type(value).__name__}")
            return default
        if minimum is not None and value < minimum:
            self.add(field_path, f"debe ser un número >= {minimum}, se encontró {value}")
            return default
        if maximum is not None and value > maximum:
            self.add(field_path, f"debe ser un número <= {maximum}, se encontró {value}")
            return default
        return float(value)

    def bool_field(self, raw: dict[str, Any], key: str, path: str, *, default: bool) -> bool:
        field_path = f"{path}.{key}"
        if key not in raw:
            return default
        value = raw[key]
        if not isinstance(value, bool):
            self.add(field_path, f"debe ser un booleano, se encontró {type(value).__name__}")
            return default
        return value

    def enum_field(
        self,
        raw: dict[str, Any],
        key: str,
        path: str,
        enum_cls: type[_E],
        *,
        default: _E,
        required: bool = False,
    ) -> _E:
        field_path = f"{path}.{key}"
        if key not in raw:
            if required:
                self.add(field_path, "campo requerido ausente")
            return default
        value = raw[key]
        if not isinstance(value, str):
            self.add(
                field_path, f"debe ser una cadena de texto, se encontró {type(value).__name__}"
            )
            return default
        for member in enum_cls:
            if member.value == value:
                return member
        allowed = ", ".join(str(member.value) for member in enum_cls)
        self.add(field_path, f"valor inválido '{value}'; se esperaba uno de: {allowed}")
        return default

    def unknown_fields(self, raw: dict[str, Any], known: frozenset[str], path: str) -> None:
        for key in raw:
            if key not in known:
                field_path = f"{path}.{key}"
                message = f"campo desconocido '{key}'"
                suggestion = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.6)
                if suggestion:
                    message += f"; ¿quiso decir '{suggestion[0]}'?"
                self.add(field_path, message)


def _email_field(v: _Validator, raw: dict[str, Any], key: str, path: str) -> str:
    field_path = f"{path}.{key}"
    if key not in raw:
        v.add(field_path, "campo requerido ausente")
        return ""
    value = raw[key]
    if not isinstance(value, str):
        v.add(field_path, f"debe ser una cadena de texto, se encontró {type(value).__name__}")
        return ""
    if _EMAIL_RE.fullmatch(value) is None:
        v.add(field_path, f"no tiene formato de email válido: '{value}'")
        return ""
    return value


_DB_FIELDS = frozenset(
    {
        "name",
        "type",
        "connection",
        "user",
        "password",
        "role",
        "charset",
        "gbak_path",
        "gbak_timeout_sec",
        "host",
        "port",
        "dbname",
        "pg_dump_path",
        "pg_dump_timeout_sec",
    }
)


def _parse_database(
    v: _Validator, raw: dict[str, Any], path: str, base_dir: Path
) -> DatabaseConfig:
    v.unknown_fields(raw, _DB_FIELDS, path)
    name = v.str_field(raw, "name", path) or ""
    type_ = v.enum_field(raw, "type", path, DbEngine, default=DbEngine.FIREBIRD, required=True)
    user = v.str_field(raw, "user", path) or ""
    password = v.str_field(raw, "password", path) or ""
    connection = v.str_field(raw, "connection", path, required=False, nullable=True)
    role = v.str_field(raw, "role", path, required=False, nullable=True)
    charset = v.str_field(raw, "charset", path, required=False, nullable=True)
    gbak_path_raw = v.str_field(raw, "gbak_path", path, required=False, nullable=True)
    gbak_path = (
        None if gbak_path_raw is None else str(normalize_path(gbak_path_raw, base_dir=base_dir))
    )
    gbak_timeout_sec = v.int_field(
        raw, "gbak_timeout_sec", path, required=False, nullable=True, exclusive_minimum=0
    )
    host = v.str_field(raw, "host", path, required=False, nullable=True)
    port = v.int_field(raw, "port", path, required=False, nullable=True, minimum=1, maximum=65535)
    dbname = v.str_field(raw, "dbname", path, required=False, nullable=True)
    pg_dump_path_raw = v.str_field(raw, "pg_dump_path", path, required=False, nullable=True)
    pg_dump_path = (
        None
        if pg_dump_path_raw is None
        else str(normalize_path(pg_dump_path_raw, base_dir=base_dir))
    )
    pg_dump_timeout_sec = v.int_field(
        raw, "pg_dump_timeout_sec", path, required=False, nullable=True, exclusive_minimum=0
    )
    return DatabaseConfig(
        name=name,
        type=type_,
        user=user,
        password=password,
        connection=connection,
        role=role,
        charset=charset,
        gbak_path=gbak_path,
        gbak_timeout_sec=gbak_timeout_sec,
        host=host,
        port=port,
        dbname=dbname,
        pg_dump_path=pg_dump_path,
        pg_dump_timeout_sec=pg_dump_timeout_sec,
    )


_AUTH_FIELDS = frozenset({"method", "password", "private_key", "passphrase"})


def _parse_auth(v: _Validator, raw: dict[str, Any], path: str, base_dir: Path) -> ServerAuth:
    v.unknown_fields(raw, _AUTH_FIELDS, path)
    method = v.enum_field(
        raw, "method", path, AuthMethod, default=AuthMethod.PASSWORD, required=True
    )
    password = v.str_field(raw, "password", path, required=False, nullable=True)
    private_key_raw = v.str_field(raw, "private_key", path, required=False, nullable=True)
    private_key = (
        None if private_key_raw is None else str(normalize_path(private_key_raw, base_dir=base_dir))
    )
    passphrase = v.str_field(raw, "passphrase", path, required=False, nullable=True)
    return ServerAuth(
        method=method, password=password, private_key=private_key, passphrase=passphrase
    )


_SERVER_FIELDS = frozenset(
    {
        "name",
        "host",
        "port",
        "username",
        "auth",
        "remote_path",
        "host_key_policy",
        "sftp_retries",
        "sftp_connect_timeout_sec",
        "sftp_operation_timeout_sec",
        "sftp_retry_backoff_base",
        "sftp_retry_max_delay_sec",
    }
)


def _parse_server(v: _Validator, raw: dict[str, Any], path: str, base_dir: Path) -> ServerConfig:
    v.unknown_fields(raw, _SERVER_FIELDS, path)
    name = v.str_field(raw, "name", path) or ""
    host = v.str_field(raw, "host", path) or ""
    port = v.int_field(raw, "port", path, minimum=1, maximum=65535) or 0
    username = v.str_field(raw, "username", path) or ""
    auth = ServerAuth(method=AuthMethod.PASSWORD)
    if "auth" not in raw:
        v.add(f"{path}.auth", "campo requerido ausente")
    else:
        auth_raw = v.mapping(raw["auth"], f"{path}.auth")
        if auth_raw is not None:
            auth = _parse_auth(v, auth_raw, f"{path}.auth", base_dir)
    remote_path = v.str_field(raw, "remote_path", path) or ""
    host_key_policy = v.enum_field(
        raw, "host_key_policy", path, HostKeyPolicy, default=HostKeyPolicy.STRICT
    )
    sftp_retries = v.int_field(raw, "sftp_retries", path, required=False, default=3, minimum=0)
    if sftp_retries is None:
        sftp_retries = 0
    sftp_connect_timeout_sec = v.int_field(
        raw, "sftp_connect_timeout_sec", path, required=False, default=30, minimum=1
    )
    if sftp_connect_timeout_sec is None:
        sftp_connect_timeout_sec = 30
    sftp_operation_timeout_sec = v.int_field(
        raw, "sftp_operation_timeout_sec", path, required=False, default=60, minimum=1
    )
    if sftp_operation_timeout_sec is None:
        sftp_operation_timeout_sec = 60
    sftp_retry_backoff_base = v.float_field(
        raw, "sftp_retry_backoff_base", path, required=False, default=2.0, minimum=0.0
    )
    if sftp_retry_backoff_base is None:
        sftp_retry_backoff_base = 2.0
    sftp_retry_max_delay_sec = v.float_field(
        raw, "sftp_retry_max_delay_sec", path, required=False, default=30.0, minimum=0.0
    )
    if sftp_retry_max_delay_sec is None:
        sftp_retry_max_delay_sec = 30.0
    return ServerConfig(
        name=name,
        host=host,
        port=port,
        username=username,
        auth=auth,
        remote_path=remote_path,
        host_key_policy=host_key_policy,
        sftp_retries=sftp_retries,
        sftp_connect_timeout_sec=sftp_connect_timeout_sec,
        sftp_operation_timeout_sec=sftp_operation_timeout_sec,
        sftp_retry_backoff_base=sftp_retry_backoff_base,
        sftp_retry_max_delay_sec=sftp_retry_max_delay_sec,
    )


_SMTP_FIELDS = frozenset({"host", "port", "starttls", "ssl", "username", "password"})


def _parse_smtp(v: _Validator, raw: dict[str, Any], path: str) -> SmtpConfig:
    v.unknown_fields(raw, _SMTP_FIELDS, path)
    host = v.str_field(raw, "host", path) or ""
    port = v.int_field(raw, "port", path, minimum=1, maximum=65535) or 0
    starttls = v.bool_field(raw, "starttls", path, default=True)
    ssl_enabled = v.bool_field(raw, "ssl", path, default=False)
    if starttls and ssl_enabled:
        v.add(
            f"{path}.ssl",
            "es mutuamente excluyente con 'starttls: true' "
            "(use 'starttls': false para SSL implícito, p. ej. puerto 465)",
        )
    username = v.str_field(raw, "username", path) or ""
    password = v.str_field(raw, "password", path) or ""
    return SmtpConfig(
        host=host,
        port=port,
        starttls=starttls,
        ssl=ssl_enabled,
        username=username,
        password=password,
    )


_NOTIFICATION_FIELDS = frozenset({"to", "from", "smtp", "log_tail_lines"})


def _parse_notification(v: _Validator, raw: dict[str, Any], path: str) -> NotificationConfig:
    v.unknown_fields(raw, _NOTIFICATION_FIELDS, path)
    to = _email_field(v, raw, "to", path)
    from_ = _email_field(v, raw, "from", path)
    smtp = SmtpConfig(host="", port=0, username="", password="")
    if "smtp" not in raw:
        v.add(f"{path}.smtp", "campo requerido ausente")
    else:
        smtp_raw = v.mapping(raw["smtp"], f"{path}.smtp")
        if smtp_raw is not None:
            smtp = _parse_smtp(v, smtp_raw, f"{path}.smtp")
    log_tail_lines = v.int_field(raw, "log_tail_lines", path, required=False, default=50, minimum=0)
    if log_tail_lines is None:
        log_tail_lines = 0
    return NotificationConfig(to=to, from_=from_, smtp=smtp, log_tail_lines=log_tail_lines)


_COMPRESSION_FIELDS = frozenset({"level", "password"})


def _parse_compression(v: _Validator, raw: dict[str, Any], path: str) -> CompressionConfig:
    v.unknown_fields(raw, _COMPRESSION_FIELDS, path)
    level = v.int_field(raw, "level", path, required=False, default=7, minimum=0, maximum=9)
    if level is None:
        level = 0
    password = v.str_field(raw, "password", path, required=False, nullable=True)
    return CompressionConfig(level=level, password=password)


_LOCAL_FIELDS = frozenset(
    {
        "work_dir",
        "retention_days",
        "log_level",
        "log_dir",
        "min_free_mb",
        "gbak_timeout_sec",
        "pg_dump_timeout_sec",
        "sftp_retries",
        "sftp_connect_timeout_sec",
    }
)


def _parse_local(v: _Validator, raw: dict[str, Any], path: str, base_dir: Path) -> LocalConfig:
    v.unknown_fields(raw, _LOCAL_FIELDS, path)
    work_dir_raw = v.str_field(raw, "work_dir", path)
    work_dir = (
        normalize_path(work_dir_raw, base_dir=base_dir) if work_dir_raw is not None else base_dir
    )
    retention_days = v.int_field(raw, "retention_days", path, minimum=0)
    if retention_days is None:
        retention_days = 0
    log_level = v.enum_field(raw, "log_level", path, LogLevel, default=LogLevel.INFO)
    log_dir_raw = v.str_field(raw, "log_dir", path, required=False, nullable=True)
    log_dir = None if log_dir_raw is None else normalize_path(log_dir_raw, base_dir=base_dir)
    min_free_mb = v.int_field(raw, "min_free_mb", path, required=False, default=1024, minimum=0)
    if min_free_mb is None:
        min_free_mb = 0
    gbak_timeout_sec = v.int_field(
        raw, "gbak_timeout_sec", path, required=False, default=7200, exclusive_minimum=0
    )
    if gbak_timeout_sec is None:
        gbak_timeout_sec = 0
    pg_dump_timeout_sec = v.int_field(
        raw, "pg_dump_timeout_sec", path, required=False, default=7200, exclusive_minimum=0
    )
    if pg_dump_timeout_sec is None:
        pg_dump_timeout_sec = 0
    sftp_retries = v.int_field(raw, "sftp_retries", path, required=False, default=3, minimum=0)
    if sftp_retries is None:
        sftp_retries = 0
    sftp_connect_timeout_sec = v.int_field(
        raw, "sftp_connect_timeout_sec", path, required=False, default=30, exclusive_minimum=0
    )
    if sftp_connect_timeout_sec is None:
        sftp_connect_timeout_sec = 0
    return LocalConfig(
        work_dir=work_dir,
        retention_days=retention_days,
        log_level=log_level,
        log_dir=log_dir,
        min_free_mb=min_free_mb,
        gbak_timeout_sec=gbak_timeout_sec,
        pg_dump_timeout_sec=pg_dump_timeout_sec,
        sftp_retries=sftp_retries,
        sftp_connect_timeout_sec=sftp_connect_timeout_sec,
    )


_JOB_FIELDS = frozenset({"databases", "schedule", "on_misfire", "skip_if_running"})


def _parse_job(
    v: _Validator, raw: dict[str, Any], path: str, timezone: ZoneInfo | None
) -> SchedulerJob:
    v.unknown_fields(raw, _JOB_FIELDS, path)
    databases: list[str] = []
    if "databases" not in raw:
        v.add(f"{path}.databases", "campo requerido ausente")
    else:
        items = v.list_field(raw["databases"], f"{path}.databases")
        if items is not None:
            if not items:
                v.add(f"{path}.databases", "debe listar al menos una base de datos")
            for index, item in enumerate(items):
                if isinstance(item, str) and item.strip():
                    databases.append(item)
                else:
                    v.add(f"{path}.databases[{index}]", "debe ser una cadena de texto no vacía")
    schedule = v.str_field(raw, "schedule", path) or ""
    if schedule:
        # Misma validación que usará el scheduler (rango y sintaxis); con la
        # timezone global ya validada, o UTC si esa también falló (así el
        # usuario ve ambos problemas de una vez).
        try:
            CronTrigger.from_crontab(schedule, timezone=timezone or ZoneInfo("UTC"))
        except ValueError as exc:
            v.add(f"{path}.schedule", f"expresión cron inválida ('{schedule}'): {exc}")
    on_misfire = v.enum_field(
        raw, "on_misfire", path, MisfirePolicy, default=MisfirePolicy.RUN_ONCE
    )
    skip_if_running = v.bool_field(raw, "skip_if_running", path, default=True)
    return SchedulerJob(
        databases=databases,
        schedule=schedule,
        on_misfire=on_misfire,
        skip_if_running=skip_if_running,
    )


_SCHEDULER_FIELDS = frozenset({"enabled", "timezone", "jobs"})


def _parse_scheduler(v: _Validator, raw: dict[str, Any], path: str) -> SchedulerConfig:
    v.unknown_fields(raw, _SCHEDULER_FIELDS, path)
    enabled = v.bool_field(raw, "enabled", path, default=False)
    timezone = v.str_field(raw, "timezone", path, required=False, default="UTC") or "UTC"
    timezone_info: ZoneInfo | None = None
    try:
        timezone_info = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        v.add(f"{path}.timezone", f"zona horaria desconocida: '{timezone}'")
    jobs: list[SchedulerJob] = []
    if "jobs" in raw:
        items = v.list_field(raw["jobs"], f"{path}.jobs")
        if items is not None:
            for index, item in enumerate(items):
                item_path = f"{path}.jobs[{index}]"
                item_map = v.mapping(item, item_path)
                if item_map is not None:
                    jobs.append(_parse_job(v, item_map, item_path, timezone_info))
    return SchedulerConfig(enabled=enabled, timezone=timezone, jobs=jobs)


_TOP_FIELDS = frozenset(
    {"databases", "compression", "servers", "notification", "local", "scheduler"}
)


def load_config(path: Path | str) -> Config:
    """Carga y valida el JSON de configuración ubicado en ``path``.

    Reporta todos los problemas estructurales de una vez vía ``ConfigError``;
    si la estructura es válida, aplica las validaciones cruzadas
    (``Config.validate_semantics``) antes de devolver el ``Config``.
    """
    config_path = Path(path)
    v = _Validator()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        problem = ConfigProblem(
            field_path=_ROOT,
            message=f"no se pudo leer el archivo de configuración: {exc}",
        )
        raise ConfigError([problem]) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        problem = ConfigProblem(
            field_path=_ROOT,
            message=f"JSON malformado: {exc.msg} (línea {exc.lineno}, columna {exc.colno})",
        )
        raise ConfigError([problem]) from exc

    root_map = v.mapping(data, _ROOT)
    if root_map is None:
        raise ConfigError(v.problems)

    base_dir = config_path.parent.absolute()
    v.unknown_fields(root_map, _TOP_FIELDS, _ROOT)

    databases: list[DatabaseConfig] = []
    if "databases" not in root_map:
        v.add(f"{_ROOT}.databases", "sección requerida ausente")
    else:
        items = v.list_field(root_map["databases"], f"{_ROOT}.databases")
        if items is not None:
            if not items:
                v.add(f"{_ROOT}.databases", "debe listar al menos una base de datos")
            for index, item in enumerate(items):
                item_path = f"{_ROOT}.databases[{index}]"
                item_map = v.mapping(item, item_path)
                if item_map is not None:
                    databases.append(_parse_database(v, item_map, item_path, base_dir))

    compression = CompressionConfig()
    if "compression" in root_map:
        section = v.mapping(root_map["compression"], f"{_ROOT}.compression")
        if section is not None:
            compression = _parse_compression(v, section, f"{_ROOT}.compression")

    servers: list[ServerConfig] = []
    if "servers" not in root_map:
        v.add(f"{_ROOT}.servers", "sección requerida ausente")
    else:
        items = v.list_field(root_map["servers"], f"{_ROOT}.servers")
        if items is not None:
            for index, item in enumerate(items):
                item_path = f"{_ROOT}.servers[{index}]"
                item_map = v.mapping(item, item_path)
                if item_map is not None:
                    servers.append(_parse_server(v, item_map, item_path, base_dir))

    notification = NotificationConfig(
        to="", from_="", smtp=SmtpConfig(host="", port=0, username="", password="")
    )
    if "notification" not in root_map:
        v.add(f"{_ROOT}.notification", "sección requerida ausente")
    else:
        section = v.mapping(root_map["notification"], f"{_ROOT}.notification")
        if section is not None:
            notification = _parse_notification(v, section, f"{_ROOT}.notification")

    local = LocalConfig(work_dir=base_dir, retention_days=0)
    if "local" not in root_map:
        v.add(f"{_ROOT}.local", "sección requerida ausente")
    else:
        section = v.mapping(root_map["local"], f"{_ROOT}.local")
        if section is not None:
            local = _parse_local(v, section, f"{_ROOT}.local", base_dir)

    scheduler = SchedulerConfig()
    if "scheduler" in root_map:
        section = v.mapping(root_map["scheduler"], f"{_ROOT}.scheduler")
        if section is not None:
            scheduler = _parse_scheduler(v, section, f"{_ROOT}.scheduler")

    if v.problems:
        raise ConfigError(v.problems)

    config = Config(
        databases=databases,
        compression=compression,
        servers=servers,
        notification=notification,
        local=local,
        scheduler=scheduler,
        config_path=config_path,
    )
    semantic_problems = config.validate_semantics()
    if semantic_problems:
        raise ConfigError(semantic_problems)
    return config
