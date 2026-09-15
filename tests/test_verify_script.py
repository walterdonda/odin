"""Tests del gate único ``scripts/verify.py`` (Item 071).

El módulo se carga por ruta con ``importlib.util`` (``scripts/`` no es un
paquete) y todos los casos usan un runner falso: la suite **nunca** ejecuta
``uv`` real.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_verify_module() -> types.ModuleType:
    path = ROOT / "scripts" / "verify.py"
    spec = importlib.util.spec_from_file_location("odin_verify_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify = _load_verify_module()


class RecordingRunner:
    """Runner falso: registra comandos y devuelve códigos/salidas por comando."""

    def __init__(
        self,
        codes: dict[str, int] | None = None,
        outputs: dict[str, str] | None = None,
        missing: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.codes = codes or {}
        self.outputs = outputs or {}
        self.missing = missing

    def __call__(
        self, command: Sequence[str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        recorded = tuple(command)
        key = " ".join(recorded)
        self.calls.append(recorded)
        if self.missing is not None and key.startswith(self.missing):
            raise FileNotFoundError(key)
        code = self.codes.get(key, 0)
        return subprocess.CompletedProcess(
            recorded, code, self.outputs.get(key, ""), ""
        )


def test_build_gates_default_order_and_commands() -> None:
    gates = verify.build_gates()
    assert [gate.id for gate in gates] == list(verify.ALL_GATE_IDS)
    assert gates[0].command == ("uv", "sync")
    assert gates[1].command == ("uv", "run", "pytest")
    assert gates[2].command == ("uv", "run", "ruff", "check", "src/odin", "tests")
    assert gates[3].command == ("uv", "run", "mypy", "src/odin")
    assert gates[4].command == (
        "uv",
        "run",
        "odin",
        "validate",
        "--config",
        "examples/config.linux.json",
    )
    assert gates[5].command == (
        "uv",
        "run",
        "odin",
        "validate",
        "--config",
        "examples/config.windows.json",
    )


def test_build_gates_quick_excludes_integration() -> None:
    gates = verify.build_gates(quick=True)
    pytest_gate = next(gate for gate in gates if gate.id == "pytest")
    assert pytest_gate.command == ("uv", "run", "pytest", "-m", "not integration")


def test_build_gates_skip_sync_removes_sync() -> None:
    ids = [gate.id for gate in verify.build_gates(skip_sync=True)]
    assert "sync" not in ids
    assert ids == list(verify.ALL_GATE_IDS[1:])


def test_build_gates_only_filters_and_preserves_order() -> None:
    ids = [gate.id for gate in verify.build_gates(only=["mypy", "sync"])]
    assert ids == ["sync", "mypy"]


def test_build_gates_only_unknown_raises_usage_error() -> None:
    with pytest.raises(verify.UsageError):
        verify.build_gates(only=["no-existe"])


def test_build_gates_only_skipped_gate_raises_usage_error() -> None:
    with pytest.raises(verify.UsageError):
        verify.build_gates(skip_sync=True, only=["sync"])


def test_main_help_output_mentions_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert verify.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "--skip-sync" in out
    assert "--quick" in out
    assert "--only" in out


def test_main_unknown_option_returns_usage_error() -> None:
    assert verify.main(["--no-existe"]) == verify.EXIT_USAGE


def test_main_unknown_only_returns_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert verify.main(["--only", "no-existe"]) == verify.EXIT_USAGE
    assert "desconocido" in capsys.readouterr().err


def test_main_runs_selected_gates_with_injected_runner() -> None:
    runner = RecordingRunner()
    code = verify.main(["--skip-sync", "--only", "ruff,mypy"], runner=runner)
    assert code == verify.EXIT_OK
    assert runner.calls == [
        ("uv", "run", "ruff", "check", "src/odin", "tests"),
        ("uv", "run", "mypy", "src/odin"),
    ]


def test_main_reports_failure_and_continues_with_remaining_gates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = RecordingRunner(
        codes={"uv run pytest -m not integration": 1},
        outputs={"uv run pytest -m not integration": "primer error\ncola-del-fallo"},
    )
    code = verify.main(["--quick"], runner=runner)
    assert code == verify.EXIT_FAILED
    assert len(runner.calls) == len(verify.ALL_GATE_IDS)
    out = capsys.readouterr().out
    assert "FALLO (código 1)" in out
    assert "cola-del-fallo" in out
    assert "1 de 6 paso(s) fallaron" in out
    assert "[OK   ] Suite de tests" not in out
    assert "[OK   ] Lint (ruff)" in out


def test_run_gate_missing_command_is_a_failure() -> None:
    runner = RecordingRunner(missing="uv")
    gate = verify.Gate("sync", "Sincronizar el entorno", ("uv", "sync"))
    result = verify.run_gate(gate, runner=runner)
    assert result.ok is False
    assert result.returncode == 127
    assert "no se pudo ejecutar 'uv'" in result.output


def test_render_step_and_summary() -> None:
    gate = verify.Gate("ruff", "Lint (ruff)", ("uv", "run", "ruff"))
    ok = verify.GateResult(gate, 0, 1.5, "")
    bad = verify.GateResult(gate, 2, 0.5, "detalle")
    step = verify.render_step(bad)
    assert "$ uv run ruff" in step
    assert "FALLO (código 2)" in step
    assert "detalle" in step
    summary = verify.render_summary([ok, bad])
    assert "[OK   ] Lint (ruff) (1.50 s)" in summary
    assert "[FALLO] Lint (ruff) (0.50 s)" in summary
    assert "1 de 2 paso(s) fallaron" in summary
    assert "en verde" in verify.render_summary([ok])
