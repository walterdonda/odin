"""Tests de humo del esqueleto del paquete (Item 001)."""

from importlib.metadata import version

import pytest

import odin
from odin.cli import main


def test_package_import_and_version() -> None:
    assert odin.__version__ == version("odin")


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert f"odin {odin.__version__}" in capsys.readouterr().out


def test_cli_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: odin" in out


def test_package_module_resolved() -> None:
    assert odin.__file__ is not None
    assert odin.__file__.endswith("__init__.py")
