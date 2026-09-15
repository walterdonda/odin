"""Tests de la retención local (Item 045): política, seguridad e idempotencia."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from odin.retention import (
    RetentionError,
    RetentionExecutor,
    is_managed_backup,
)

NOW = 1_000_000.0
DAY = 86400.0


def _touch(path: Path, mtime: float, content: bytes = b"x") -> Path:
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))
    return path


def _executor(now: float = NOW) -> RetentionExecutor:
    return RetentionExecutor(now=lambda: now)


# --- convención de nombres ---


@pytest.mark.parametrize(
    "name",
    [
        "erp_principal_20260915_011119.fbk",
        "erp_principal_20260915_011119.fbk.7z",
        "base con espacios_20260915_011119.fbk",
        "bd_2_20200101_000000.fbk.7z",
    ],
)
def test_managed_backup_convention_accepts_odin_artifacts(name: str) -> None:
    assert is_managed_backup(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "config.json",
        "odin.log",
        "notas.fbk.txt",
        "erp.fbk",
        "erp_2026.fbk",
        "erp_20260915.fbk",
        "erp_20260915_0111.fbk",
        "erp_20260915_011119.zip",
        "erp_20260915_011119.fbk.bak",
        "erp_20260915_011119.fbk.7z.tmp",
        "_20260915_011119.fbk.7z",
    ],
)
def test_managed_backup_convention_rejects_foreign_names(name: str) -> None:
    assert is_managed_backup(name) is False


# --- política de edad ---


def test_deletes_only_old_managed_artifacts(tmp_path: Path) -> None:
    old_fbk = _touch(tmp_path / "erp_20200101_000000.fbk", NOW - 30 * DAY, b"a" * 10)
    old_7z = _touch(tmp_path / "erp_20200101_000000.fbk.7z", NOW - 30 * DAY, b"b" * 25)
    recent = _touch(tmp_path / "erp_20260915_011119.fbk.7z", NOW - DAY)
    foreign = _touch(tmp_path / "config.json", NOW - 300 * DAY)
    log = _touch(tmp_path / "odin.log", NOW - 300 * DAY)
    notes = _touch(tmp_path / "notas.fbk.txt", NOW - 300 * DAY)

    result = _executor().run_retention(tmp_path, retention_days=7)

    assert result.enabled is True
    assert result.deleted == 2
    assert result.examined == 3
    assert result.freed_bytes == 35
    assert result.errors == ()
    assert not old_fbk.exists()
    assert not old_7z.exists()
    assert recent.exists()
    assert foreign.exists()
    assert log.exists()
    assert notes.exists()


def test_cutoff_boundary_is_strict(tmp_path: Path) -> None:
    cutoff = NOW - 7 * DAY
    before = _touch(tmp_path / "antes_20200101_000000.fbk", cutoff - 1)
    exactly = _touch(tmp_path / "justo_20200101_000000.fbk", cutoff)
    after = _touch(tmp_path / "despues_20200101_000000.fbk", cutoff + 1)

    result = _executor().run_retention(tmp_path, retention_days=7)

    assert result.deleted == 1
    assert result.examined == 3
    assert not before.exists()
    assert exactly.exists()
    assert after.exists()


def test_recent_artifacts_are_protected_by_run_start(tmp_path: Path) -> None:
    run_start = NOW - 100_000.0
    protected = _touch(tmp_path / "corrida_20200101_000000.fbk", run_start)
    from_previous_run = _touch(tmp_path / "previa_20200101_000000.fbk", run_start - 1)

    result = _executor().run_retention(
        tmp_path, retention_days=1, run_started_at=run_start
    )

    assert result.deleted == 1
    assert protected.exists()
    assert not from_previous_run.exists()


def test_retention_days_zero_is_noop(tmp_path: Path) -> None:
    old = _touch(tmp_path / "erp_20200101_000000.fbk", NOW - 300 * DAY)

    result = _executor().run_retention(tmp_path, retention_days=0)

    assert result.enabled is False
    assert result.deleted == 0
    assert result.examined == 0
    assert old.exists()


def test_negative_retention_days_is_noop(tmp_path: Path) -> None:
    old = _touch(tmp_path / "erp_20200101_000000.fbk", NOW - 300 * DAY)

    result = _executor().run_retention(tmp_path, retention_days=-5)

    assert result.enabled is False
    assert old.exists()


def test_missing_work_dir_is_noop(tmp_path: Path) -> None:
    result = _executor().run_retention(tmp_path / "no-existe", retention_days=7)

    assert result.enabled is True
    assert result.examined == 0
    assert result.deleted == 0
    assert result.errors == ()


# --- seguridad ---


def test_subdirectories_and_symlinks_are_ignored(tmp_path: Path) -> None:
    managed_dir = tmp_path / "dir_20200101_000000.fbk"
    managed_dir.mkdir()
    target = _touch(tmp_path / "afuera.fbk", NOW - 300 * DAY, b"t" * 7)
    link = tmp_path / "enlace_20200101_000000.fbk"
    link.symlink_to(target)

    result = _executor().run_retention(tmp_path, retention_days=7)

    assert result.examined == 2
    assert result.deleted == 0
    assert managed_dir.is_dir()
    assert link.is_symlink()
    assert target.exists()


def test_delete_error_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rota = _touch(tmp_path / "rota_20200101_000000.fbk", NOW - 300 * DAY)
    buena = _touch(tmp_path / "buena_20200101_000000.fbk.7z", NOW - 300 * DAY, b"z" * 3)
    original_unlink = Path.unlink

    def flaky_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name.startswith("rota"):
            raise PermissionError(13, "permiso denegado")
        original_unlink(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    result = _executor().run_retention(tmp_path, retention_days=7)

    assert result.deleted == 1
    assert result.examined == 2
    assert rota.exists()
    assert not buena.exists()
    assert result.errors == (
        RetentionError(path=str(rota), message="[Errno 13] permiso denegado"),
    )


def test_idempotent_second_pass(tmp_path: Path) -> None:
    _touch(tmp_path / "erp_20200101_000000.fbk", NOW - 300 * DAY)
    _touch(tmp_path / "erp_20200101_000000.fbk.7z", NOW - 300 * DAY)

    first = _executor().run_retention(tmp_path, retention_days=7)
    second = _executor().run_retention(tmp_path, retention_days=7)

    assert first.deleted == 2
    assert second.deleted == 0
    assert second.examined == 0
    assert second.freed_bytes == 0
    assert second.errors == ()


def test_foreign_managed_lookalikes_are_untouched(tmp_path: Path) -> None:
    lookalikes = [
        _touch(tmp_path / "erp_20260915_011119.fbk.bak", NOW - 300 * DAY),
        _touch(tmp_path / "erp_2026_011119.fbk", NOW - 300 * DAY),
        _touch(tmp_path / "erp_20260915_011119.zip", NOW - 300 * DAY),
    ]

    result = _executor().run_retention(tmp_path, retention_days=7)

    assert result.examined == 0
    assert result.deleted == 0
    assert all(path.exists() for path in lookalikes)
