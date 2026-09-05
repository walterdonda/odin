"""Tests de normalización OS-agnóstica de rutas (Item 003)."""

import getpass
import os
from pathlib import Path

import pytest

from odin.paths import expand_user, is_windows_flavor, normalize_path

BASE = Path("/base/config-dir")


def test_posix_absolute_not_prefixed() -> None:
    result = normalize_path("/var/backups/odin", base_dir=BASE)
    assert result.as_posix() == "/var/backups/odin"


def test_windows_drive_not_prefixed_on_any_os() -> None:
    result = normalize_path("D:\\Backups\\odin", base_dir=BASE)
    assert result.as_posix() == "D:/Backups/odin"


def test_windows_drive_with_slashes() -> None:
    result = normalize_path("C:/Datos/erp.fdb", base_dir=BASE)
    assert result.as_posix() == "C:/Datos/erp.fdb"


def test_windows_unc() -> None:
    result = normalize_path("\\\\srv\\share\\backups", base_dir=BASE)
    assert result.as_posix() == "//srv/share/backups"


def test_mixed_separators_normalized() -> None:
    result = normalize_path("C:/Datos\\ERP\\erp.fdb", base_dir=BASE)
    assert result.as_posix() == "C:/Datos/ERP/erp.fdb"


def test_drive_relative_without_base_kept() -> None:
    result = normalize_path("D:file.fdb")
    assert result.as_posix() == "D:file.fdb"


def test_tilde_posix_separators() -> None:
    result = normalize_path("~/.ssh/id_ed25519")
    assert result.as_posix() == (Path.home() / ".ssh/id_ed25519").as_posix()


def test_tilde_windows_separators() -> None:
    result = normalize_path("~\\.ssh\\id_ed25519")
    assert result.as_posix() == (Path.home() / ".ssh/id_ed25519").as_posix()


def test_tilde_alone() -> None:
    assert normalize_path("~") == Path.home()


@pytest.mark.skipif(os.name == "nt", reason="ntpath no resuelve ~usuario")
def test_tilde_user_posix() -> None:
    user = getpass.getuser()
    result = normalize_path(f"~{user}/data", base_dir=BASE)
    assert result.as_posix() == (Path.home() / "data").as_posix()


def test_expand_user_delegates_tilde_user() -> None:
    user = getpass.getuser()
    assert expand_user(f"~{user}/x") == os.path.expanduser(f"~{user}") + "/x"


def test_relative_resolved_against_base() -> None:
    assert normalize_path("logs", base_dir=BASE).as_posix() == "/base/config-dir/logs"


def test_relative_with_dot_prefix() -> None:
    assert normalize_path("./work", base_dir=BASE).as_posix() == "/base/config-dir/work"


def test_relative_with_backslashes() -> None:
    assert normalize_path("bin\\gbak", base_dir=BASE).as_posix() == "/base/config-dir/bin/gbak"


def test_relative_without_base_kept_relative() -> None:
    assert normalize_path("logs").as_posix() == "logs"


def test_double_slash_posix_is_absolute() -> None:
    result = normalize_path("//srv/share", base_dir=BASE)
    assert result.as_posix() == "//srv/share"


def test_whitespace_stripped() -> None:
    assert normalize_path("  /var/x  ", base_dir=BASE).as_posix() == "/var/x"


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_raises(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_path(raw, base_dir=BASE)


def test_dotdot_not_collapsed() -> None:
    result = normalize_path("a/../b", base_dir=BASE)
    assert result.as_posix() == "/base/config-dir/a/../b"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:\\x", True),
        ("C:/x", True),
        ("D:file", True),
        ("\\\\srv\\x", True),
        ("/var/x", False),
        ("relative/path", False),
        ("//srv/x", False),
    ],
)
def test_is_windows_flavor(raw: str, expected: bool) -> None:
    assert is_windows_flavor(raw) is expected


def test_expand_user_no_tilde_unchanged() -> None:
    assert expand_user("/a/~b/c") == "/a/~b/c"
    assert expand_user("a~b") == "a~b"


@pytest.mark.parametrize(
    "raw",
    ["/var/backups/odin", "D:\\Backups\\odin", "./work", "~/.ssh/id_ed25519", "bin\\gbak"],
)
def test_normalization_idempotent(raw: str) -> None:
    first = normalize_path(raw, base_dir=BASE)
    second = normalize_path(str(first), base_dir=BASE)
    assert first == second
