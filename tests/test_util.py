"""Unit tests for pure helpers."""

from __future__ import annotations

from pathlib import Path

from imount.backends.mirror import MirrorStats, _is_fresh, _rel_dir
from imount.util import default_volume_name, human_size


def test_rel_dir() -> None:
    assert _rel_dir("/DCIM", "/DCIM") == ""
    assert _rel_dir("/DCIM/100APPLE", "/DCIM") == "100APPLE"
    assert _rel_dir("/DCIM/100APPLE/A", "/DCIM") == "100APPLE/A"
    assert _rel_dir("/other", "/DCIM") == ""


def test_is_fresh(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"hello")
    mtime = target.stat().st_mtime
    assert _is_fresh(target, 5, mtime)
    assert not _is_fresh(target, 6, mtime)
    assert not _is_fresh(target, 5, mtime + 10.0)
    assert not _is_fresh(tmp_path / "missing", 5, mtime)


def test_human_size() -> None:
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.0 KiB"
    assert human_size(1024 * 1024 * 3) == "3.0 MiB"


def test_default_volume_name() -> None:
    assert default_volume_name("Calamus iPhone", "/DCIM") == "Calamus iPhone-DCIM"
    assert default_volume_name(None, "/") == "iOS Device-Media"
    assert default_volume_name("张三的 iPhone", "/DCIM").endswith("-DCIM")


def test_mirror_stats_summary() -> None:
    stats = MirrorStats(copied=2, skipped=1, bytes_copied=2048, dirs_created=1, deleted=0, errors=0)
    text = stats.summary()
    assert "复制 2 个文件" in text
    assert "2.0 KiB" in text
