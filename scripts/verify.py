#!/usr/bin/env python3
"""Gate único de verificación de ODIN (Item 071).

Corre en orden los gates del proyecto y resume el resultado, con el mismo
comportamiento en Linux y Windows (solo stdlib, comandos como listas de
argumentos y ``uv`` resuelto del ``PATH``, ``uv.exe`` en Windows)::

    uv run python scripts/verify.py            # todos los gates
    uv run python scripts/verify.py --quick    # omite los tests @integration
    uv run python scripts/verify.py --only ruff,mypy
    uv run python scripts/verify.py --skip-sync --only validate-linux

Pasos e ids:

- ``sync``              ``uv sync``
- ``pytest``            ``uv run pytest`` (``-m "not integration"`` con ``--quick``)
- ``ruff``              ``uv run ruff check src/odin tests``
- ``mypy``              ``uv run mypy src/odin``
- ``validate-linux``    ``uv run odin validate --config examples/config.linux.json``
- ``validate-windows``  ``uv run odin validate --config examples/config.windows.json``

Todos los pasos seleccionados se ejecutan aunque uno falle (para tener el
panorama completo en una sola corrida). Cada uno imprime el comando, su
duración y su estado; los fallos suman las últimas líneas de su salida y el
resumen final queda en el exit code:

- ``0``: todos los pasos seleccionados pasan.
- ``1``: al menos un paso falla.
- ``2``: argumentos inválidos (p. ej. un id desconocido en ``--only`` o una
  selección vacía), igual que el criterio de la CLI de ODIN.

Este script es el gate local equivalente de la CI (Item 073) y la lógica
pura (``build_gates``/``run_gate``/``render_step``/``render_summary``) está
cubierta por ``tests/test_verify_script.py`` con el runner inyectable, sin
ejecutar ``uv``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

UV = "uv"

OUTPUT_TAIL_LINES = 20

ALL_GATE_IDS = (
    "sync",
    "pytest",
    "ruff",
    "mypy",
    "validate-linux",
    "validate-windows",
)


class UsageError(Exception):
    """Selección de gates inválida (id desconocido o selección vacía)."""


@dataclass(frozen=True, slots=True)
class Gate:
    """Un paso del gate: id estable, etiqueta legible y comando argv."""

    id: str
    label: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateResult:
    """Resultado de un gate: código, duración y salida combinada."""

    gate: Gate
    returncode: int
    duration_seconds: float
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def _default_runner(
    command: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), cwd=cwd, capture_output=True, text=True)


def build_gates(
    *,
    quick: bool = False,
    skip_sync: bool = False,
    only: Sequence[str] = (),
) -> list[Gate]:
    """Construye la lista de gates en orden canónico según los flags.

    ``only`` selecciona un subconjunto por id preservando el orden canónico.
    Un id desconocido o una selección que queda vacía (p. ej. ``--skip-sync
    --only sync``) lanzan ``UsageError``.
    """
    gates = [
        Gate("sync", "Sincronizar el entorno", (UV, "sync")),
        Gate(
            "pytest",
            "Suite de tests",
            (UV, "run", "pytest") + (("-m", "not integration") if quick else ()),
        ),
        Gate("ruff", "Lint (ruff)", (UV, "run", "ruff", "check", "src/odin", "tests")),
        Gate("mypy", "Tipado (mypy)", (UV, "run", "mypy", "src/odin")),
        Gate(
            "validate-linux",
            "Validar examples/config.linux.json",
            (UV, "run", "odin", "validate", "--config", "examples/config.linux.json"),
        ),
        Gate(
            "validate-windows",
            "Validar examples/config.windows.json",
            (UV, "run", "odin", "validate", "--config", "examples/config.windows.json"),
        ),
    ]
    if skip_sync:
        gates = [gate for gate in gates if gate.id != "sync"]
    if not only:
        return gates
    wanted = set(only)
    unknown = sorted(wanted - set(ALL_GATE_IDS))
    if unknown:
        raise UsageError(
            f"id(s) desconocido(s) en --only: {', '.join(unknown)} "
            f"(válidos: {', '.join(ALL_GATE_IDS)})"
        )
    selected = [gate for gate in gates if gate.id in wanted]
    if not selected:
        raise UsageError("--only no seleccionó ningún paso ejecutable")
    return selected


def run_gate(gate: Gate, *, runner: Runner | None = None, cwd: Path = ROOT) -> GateResult:
    """Ejecuta un gate con el runner inyectable (subprocess real por defecto)."""
    execute = runner or _default_runner
    started = time.perf_counter()
    try:
        completed = execute(list(gate.command), cwd)
    except OSError as exc:
        duration = time.perf_counter() - started
        return GateResult(
            gate=gate,
            returncode=127,
            duration_seconds=duration,
            output=f"no se pudo ejecutar '{gate.command[0]}': {exc}",
        )
    duration = time.perf_counter() - started
    output = f"{completed.stdout or ''}{completed.stderr or ''}"
    return GateResult(
        gate=gate,
        returncode=completed.returncode,
        duration_seconds=duration,
        output=output,
    )


def _format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def render_step(result: GateResult) -> str:
    """Bloque de un paso: comando, duración y estado (con cola si falla)."""
    status = "OK" if result.ok else f"FALLO (código {result.returncode})"
    lines = [
        f"==> {result.gate.label}",
        f"    $ {_format_command(result.gate.command)}",
        f"    {status} en {result.duration_seconds:.2f} s",
    ]
    if not result.ok and result.output.strip():
        tail = result.output.strip().splitlines()[-OUTPUT_TAIL_LINES:]
        lines.append(f"    --- últimas {len(tail)} línea(s) ---")
        lines.extend(f"    {line}" for line in tail)
    return "\n".join(lines)


def render_summary(results: Sequence[GateResult]) -> str:
    """Resumen final: estado por paso y resultado global."""
    lines = ["", "Resumen:"]
    for result in results:
        status = "OK   " if result.ok else "FALLO"
        lines.append(
            f"  [{status}] {result.gate.label} ({result.duration_seconds:.2f} s)"
        )
    failed = sum(1 for result in results if not result.ok)
    if failed:
        lines.append(f"Resultado: FALLO — {failed} de {len(results)} paso(s) fallaron")
    else:
        lines.append(f"Resultado: OK — {len(results)} paso(s) en verde")
    return "\n".join(lines)


def _split_only(values: Sequence[str] | None) -> list[str]:
    ids: list[str] = []
    for value in values or []:
        ids.extend(piece.strip() for piece in value.split(",") if piece.strip())
    return ids


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/verify.py",
        description=(
            "Gate único de ODIN: corre los gates del proyecto en orden y "
            "resume el resultado (exit 0 solo si todo pasa)."
        ),
        epilog=f"ids de --only: {', '.join(ALL_GATE_IDS)}.",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="omite 'uv sync' (entorno ya sincronizado)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="excluye los tests marcados integration ('-m \"not integration\"')",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="ID[,ID...]",
        help="corre solo los pasos indicados (repetible o separados por comas)",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    """Punto de entrada: devuelve el exit code (0/1/2) en lugar de lanzarlo."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help y errores de sintaxis de argparse
        return int(exc.code or EXIT_OK)

    try:
        gates = build_gates(
            quick=bool(args.quick),
            skip_sync=bool(args.skip_sync),
            only=_split_only(args.only),
        )
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"Gate de ODIN — {len(gates)} paso(s) en {ROOT}")
    results: list[GateResult] = []
    for gate in gates:
        print(f"Ejecutando: {gate.label} ...", flush=True)
        result = run_gate(gate, runner=runner)
        results.append(result)
        print(render_step(result), flush=True)
    print(render_summary(results))
    return EXIT_OK if all(result.ok for result in results) else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
