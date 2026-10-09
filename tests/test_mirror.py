"""Tests for the incremental mirror backend using the fake AFC."""

from __future__ import annotations

import os
from pathlib import Path

from imount.backends import mirror


async def test_mirror_copies_tree(local_afc, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    stats = await mirror.mirror(local_afc, "/", dest)

    assert stats.copied == 3
    assert stats.errors == 0
    assert (dest / "100APPLE" / "IMG_0001.JPG").read_bytes() == b"\xff\xd8" + b"a" * 2046
    assert (dest / "101APPLE" / "IMG_0003.MOV").exists()


async def test_mirror_is_incremental(local_afc, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    first = await mirror.mirror(local_afc, "/", dest)
    assert first.copied == 3
    second = await mirror.mirror(local_afc, "/", dest)
    assert second.copied == 0
    assert second.skipped == 3


async def test_mirror_dry_run(local_afc, tmp_path: Path) -> None:
    dest = tmp_path / "dry"
    stats = await mirror.mirror(local_afc, "/", dest, dry_run=True)
    assert stats.copied == 3
    assert not dest.exists() or not any(dest.iterdir())


async def test_mirror_delete_prunes(local_afc, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    await mirror.mirror(local_afc, "/", dest)
    extra = dest / "100APPLE" / "STALE.JPG"
    extra.write_bytes(b"junk")

    stats = await mirror.mirror(local_afc, "/", dest, delete=True)
    assert stats.deleted == 1
    assert not extra.exists()


async def test_mirror_subdir(local_afc, tmp_path: Path) -> None:
    dest = tmp_path / "sub"
    stats = await mirror.mirror(local_afc, "/100APPLE", dest)
    assert stats.copied == 2
    assert sorted(p.name for p in dest.iterdir()) == ["IMG_0001.JPG", "IMG_0002.JPG"]
