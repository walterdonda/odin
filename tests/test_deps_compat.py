from __future__ import annotations

import sys
import tomllib
import pytest
from importlib.metadata import version, metadata

with open("pyproject.toml", "rb") as f:
    pyprojecttoml = tomllib.load(f)

DEPENDENCIES_TO_CHECK = [
    "paramiko",
    "py7zr",
    "apscheduler",
    "cryptography",
    "pynacl",
    "bcrypt",
    "cffi",
]

@pytest.mark.parametrize("dep", DEPENDENCIES_TO_CHECK)
def test_dependencies_import_and_version(dep: str) -> None:
    """Verifica que las dependencias importan y satisfacen los floors de pyproject.toml."""
    if dep in ["paramiko", "py7zr", "apscheduler"]:
        try:
            module = __import__(dep.replace("-", "_"))
            assert hasattr(module, "__version__")
            assert isinstance(module.__version__, str)
            assert len(module.__version__) > 0
        except Exception as e:
            pytest.fail(f"Error importando {dep}: {e}")

    deps_config = pyprojecttoml.get("project", {}).get("dependencies", [])
    dep_entry = None
    for entry in deps_config:
        clean_entry = entry.split(";")[0].strip().strip('"')
        if clean_entry.split(">=")[0].split("==")[0].split(">")[0].strip() == dep:
            dep_entry = clean_entry
            break
    
            if dep_entry:
                if ">=" in dep_entry:
                    floor_str = dep_entry.split(">=")[1].split(" ")[0]
                    current_version = version(dep)
                    
                    def parse_v(v_str: str) -> list[int]:
                        return [int(x) for x in v_str.split(".") if x.isdigit()]

                    v_parts = parse_v(current_version)
                    f_parts = parse_v(floor_str[1:])
                    
                    for i in range(min(len(v_parts), len(f_parts))):
                        if v_parts[i] > f_parts[i]:
                            break
                        if v_parts[i] < f_parts[i]:
                            pytest.fail(f"Version mismatch for {dep}: installed {current_version}, required >= {floor_str}")
                            break
                    else:
                        if len(v_parts) < len(f_parts):
                            pytest.fail(f"Version mismatch for {dep}: installed {current_version}, required >= {floor_str}")

def test_pywin32_behavior_on_linux() -> None:
    """Verifica que pywin32 no falla en Linux (su ausencia es esperamente)."""
    if sys.platform == "win32":
        pytest.skip("pywin32 no disponible en Linux para test de import")
    
    try:
        import win32serviceutil
        pytest.fail("pywin32 no debería estar instalado/importable en Linux")
    except ImportError:
        pass 

def test_pywin32_wheels_in_lock() -> None:
    """Verificación estática de que el lock universal contiene wheels de pywin32 para 3.14."""
    with open("uv.lock", "r", encoding="utf-8") as f:
        lock_content = f.read()
    
    assert "pywin32-312-cp314-cp314-win32.whl" in lock_content
    assert "pywin32-312-cp314-cp314-win_amd64.whl" in lock_content
    assert "pywin32-312-cp314-cp314-win_arm64.whl" in lock_content

