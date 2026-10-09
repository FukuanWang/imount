"""Shared fixtures for the imount test-suite.

The real :class:`imount.local_afc.LocalAfc` is used as a device stand-in so the
complete WebDAV provider + mount lifecycle can be exercised without hardware.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imount.local_afc import LocalAfc


@pytest.fixture()
def local_tree(tmp_path: Path) -> Path:
    """A small DCIM-like tree with nested directories and binary files."""
    root = tmp_path / "device"
    (root / "100APPLE").mkdir(parents=True)
    (root / "101APPLE").mkdir(parents=True)
    (root / "100APPLE" / "IMG_0001.JPG").write_bytes(b"\xff\xd8" + b"a" * 2046)
    (root / "100APPLE" / "IMG_0002.JPG").write_bytes(b"\xff\xd8" + b"b" * 4094)
    (root / "101APPLE" / "IMG_0003.MOV").write_bytes(b"\x00\x00" + b"c" * 8190)
    return root


@pytest.fixture()
def local_afc(local_tree: Path) -> LocalAfc:
    return LocalAfc(local_tree)
