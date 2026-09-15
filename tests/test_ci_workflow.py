"""Contrato estructural del workflow de CI (`.github/workflows/ci.yml`, Item 073).

El repositorio no tiene remoto todavía, así que la CI no se ha ejecutado: este
test mantiene el YAML como contrato verificable en local (estructura de los
jobs, gate único del Item 071, artefacto del wheel, `permissions` de solo
lectura, ausencia de secretos y el smoke de Windows del Item 073), para que al
publicar el repositorio el workflow no derive en silencio.

Se parsea con PyYAML (`pyyaml` en el grupo `dev`). Ojo: YAML 1.1 lee la clave
`on` como el booleano `True`; el helper `_triggers` normaliza ambas formas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SMOKE_TEST_PATH = REPO_ROOT / "tests" / "test_service_windows_integration.py"
VERIFY_SCRIPT = "scripts/verify.py"
SMOKE_ENV_VAR = "ODIN_WINDOWS_SERVICE_SMOKE"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict[str, Any]:
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict), "el workflow debe ser un mapeo YAML"
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el bloque `on` normalizando la clave booleana de YAML 1.1."""
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict), "el workflow debe declarar disparadores (`on`)"
    return value


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, "el job debe declarar pasos"
    return steps


def _run_commands(job: dict[str, Any]) -> list[str]:
    return [str(step["run"]) for step in _steps(job) if "run" in step]


def _uses(job: dict[str, Any]) -> list[str]:
    return [str(step["uses"]) for step in _steps(job) if "uses" in step]


def _step_with_uses(job: dict[str, Any], prefix: str) -> dict[str, Any]:
    matches = [step for step in _steps(job) if str(step.get("uses", "")).startswith(prefix)]
    assert matches, f"falta el paso '{prefix}'"
    return matches[0]


def _assert_job_is_verified(job: dict[str, Any]) -> None:
    """Pasos compartidos: checkout, uv con caché, gate, build y artefacto."""
    assert any(uses.startswith("actions/checkout@") for uses in _uses(job))
    setup_uv = _step_with_uses(job, "astral-sh/setup-uv@")
    assert setup_uv.get("with", {}).get("enable-cache") is True

    commands = _run_commands(job)
    assert any(command.startswith("uv sync") for command in commands), "falta 'uv sync'"
    assert any(VERIFY_SCRIPT in command for command in commands), f"falta el gate {VERIFY_SCRIPT}"
    assert any(command.startswith("uv build") for command in commands), "falta 'uv build'"

    artifact = _step_with_uses(job, "actions/upload-artifact@")
    artifact_config = artifact.get("with", {})
    assert artifact_config.get("path") == "dist/*.whl"
    assert artifact_config.get("name")


def test_workflow_file_exists_and_is_valid_yaml(workflow: dict[str, Any]) -> None:
    assert WORKFLOW_PATH.is_file()
    assert workflow.get("name")
    assert set(_triggers(workflow)) >= {"push", "pull_request"}


def test_workflow_is_read_only_and_has_no_secrets(
    workflow_text: str, workflow: dict[str, Any]
) -> None:
    assert workflow.get("permissions") == {"contents": "read"}
    assert "secrets." not in workflow_text


def test_both_platform_jobs_run_the_single_gate(workflow: dict[str, Any]) -> None:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    assert set(jobs) >= {"linux", "windows"}

    linux = jobs["linux"]
    windows = jobs["windows"]
    assert linux.get("runs-on") == "ubuntu-latest"
    assert windows.get("runs-on") == "windows-latest"
    _assert_job_is_verified(linux)
    _assert_job_is_verified(windows)


def test_linux_job_artifact_name_is_distinct(workflow: dict[str, Any]) -> None:
    jobs = workflow["jobs"]
    linux_artifact = _step_with_uses(jobs["linux"], "actions/upload-artifact@")
    windows_artifact = _step_with_uses(jobs["windows"], "actions/upload-artifact@")
    assert linux_artifact["with"]["name"] != windows_artifact["with"]["name"]


def test_windows_job_runs_the_gated_service_smoke(workflow: dict[str, Any]) -> None:
    windows = workflow["jobs"]["windows"]
    smoke_steps = [
        step
        for step in _steps(windows)
        if SMOKE_ENV_VAR in str(step.get("env", {})) or "smoke" in str(step.get("name", "")).lower()
    ]
    assert smoke_steps, "el job Windows debe ejecutar el smoke gated del servicio"
    smoke = smoke_steps[0]
    assert smoke.get("env", {}).get(SMOKE_ENV_VAR) == "1"
    assert "tests/test_service_windows_integration.py" in str(smoke.get("run", ""))

    linux = workflow["jobs"]["linux"]
    assert all(SMOKE_ENV_VAR not in str(step.get("env", {})) for step in _steps(linux))


def test_smoke_test_module_is_gated_and_marked_integration() -> None:
    assert SMOKE_TEST_PATH.is_file()
    text = SMOKE_TEST_PATH.read_text(encoding="utf-8")
    assert f'"{SMOKE_ENV_VAR}"' in text
    assert "pytest.mark.integration" in text
    assert "pytest.mark.skipif" in text
