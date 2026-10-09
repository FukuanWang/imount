"""One-way mirror (sync) backend.

This is a fallback for when a real mount is not desired/possible: it copies the
device tree to a local directory, skipping files whose size and modification
time already match.  It never deletes local files unless ``delete=True``.
"""

from __future__ import annotations

import asyncio
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Optional

from ..errors import AfcPathError
from ..util import human_size

# mtime differences below this many seconds are treated as "same file"
_MTIME_TOLERANCE = 2.0


@dataclass
class MirrorStats:
    """Result counters for a mirror run."""

    copied: int = 0
    skipped: int = 0
    bytes_copied: int = 0
    dirs_created: int = 0
    deleted: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"复制 {self.copied} 个文件（{human_size(self.bytes_copied)}），"
            f"跳过 {self.skipped} 个，新建目录 {self.dirs_created} 个，"
            f"删除 {self.deleted} 个，错误 {self.errors} 个。"
        )


def _rel_dir(folder: str, src: str) -> str:
    """Return ``folder`` relative to ``src`` as a POSIX string (``""`` for the root)."""
    try:
        rel = PurePosixPath(folder).relative_to(PurePosixPath(src))
    except ValueError:
        return ""
    text = str(rel)
    return "" if text == "." else text


def _mtime(stat: dict[str, Any]) -> Optional[float]:
    value = stat.get("st_mtime")
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_fresh(local: Path, size: int, mtime: Optional[float]) -> bool:
    try:
        info = local.stat()
    except OSError:
        return False
    if info.st_size != size:
        return False
    if mtime is not None and abs(info.st_mtime - mtime) > _MTIME_TOLERANCE:
        return False
    return True


def _prune(dest: Path, known_files: set[str], known_dirs: set[str]) -> int:
    """Remove local entries that are not part of the mirrored device tree."""
    removed = 0
    for root, dirs, files in os.walk(dest, topdown=False):
        root_path = Path(root)
        rel_root = "" if root_path == dest else root_path.relative_to(dest).as_posix()
        for name in files:
            rel = posixpath.join(rel_root, name) if rel_root else name
            if rel not in known_files:
                try:
                    (root_path / name).unlink()
                    removed += 1
                except OSError:
                    pass
        for name in dirs:
            rel = posixpath.join(rel_root, name) if rel_root else name
            if rel not in known_dirs:
                try:
                    (root_path / name).rmdir()
                    removed += 1
                except OSError:
                    pass
    return removed


async def mirror(
    afc: Any,
    src: str,
    dest: Path,
    *,
    delete: bool = False,
    dry_run: bool = False,
    include_hidden: bool = True,
    on_file: Optional[Callable[[str, str], None]] = None,
) -> MirrorStats:
    """Mirror the device directory ``src`` into local ``dest``.

    :param afc: an open :class:`AfcService`.
    :param src: device source directory (``/`` is the AFC Media root).
    :param dest: local destination directory (created if missing).
    :param delete: remove local files/dirs missing from the device after copying.
    :param dry_run: report what would happen without touching the filesystem.
    :param include_hidden: copy dot-files (default ``True``).
    :param on_file: optional ``callback(action, path)`` invoked per file.
    """
    src = "/" + src.strip("/")
    if not await afc.exists(src):
        raise AfcPathError(f"设备上不存在路径：{src}")

    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    stats = MirrorStats()
    known_files: set[str] = set()
    known_dirs: set[str] = {""}

    def emit(action: str, path: str) -> None:
        if on_file is not None:
            on_file(action, path)

    async for folder, _dirs, files in afc.walk(src):
        rel_dir = _rel_dir(folder, src)
        local_dir = dest / rel_dir if rel_dir else dest
        if rel_dir:
            known_dirs.add(rel_dir)
        if not dry_run and not local_dir.exists():
            local_dir.mkdir(parents=True, exist_ok=True)
            stats.dirs_created += 1

        for name in list(files):
            if not include_hidden and name.startswith("."):
                continue
            rel = posixpath.join(rel_dir, name) if rel_dir else name
            remote = posixpath.join(folder, name)
            local = dest / rel
            known_files.add(rel)

            try:
                stat = await afc.stat(remote)
            except Exception:  # noqa: BLE001 - keep going on individual failures
                stats.errors += 1
                emit("error", rel)
                continue

            size = int(stat.get("st_size", 0) or 0)
            mtime = _mtime(stat)

            if _is_fresh(local, size, mtime):
                stats.skipped += 1
                continue

            if dry_run:
                stats.copied += 1
                stats.bytes_copied += size
                emit("copy", rel)
                continue

            try:
                local.parent.mkdir(parents=True, exist_ok=True)
                await afc.pull(remote, str(local), progress_bar=False)
                if mtime is not None:
                    os.utime(local, (mtime, mtime))
                stats.copied += 1
                stats.bytes_copied += size
                emit("copy", rel)
            except Exception:  # noqa: BLE001
                stats.errors += 1
                emit("error", rel)

    if delete and not dry_run:
        stats.deleted = _prune(dest, known_files, known_dirs)

    return stats
