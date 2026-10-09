"""A local-directory-backed implementation of the AFC surface used by the
WebDAV provider.

This is used by the ``imount demo`` command (and the test-suite) to exercise
the complete mount pipeline — WebDAV server, ``mount_webdav``, lifecycle — on a
plain folder, without an iOS device attached.

Only the operations needed for a mounted volume are implemented.  The object
mimics the subset of :class:`pymobiledevice3.services.afc.AfcService` that the
WebDAV provider and the mirror backend call.
"""

from __future__ import annotations

import asyncio
import os
import posixpath
import shutil
import stat as stat_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # keep the stand-in compatible with the real AFC error contract
    from pymobiledevice3.exceptions import AfcFileNotFoundError
except ImportError:  # pragma: no cover

    class AfcFileNotFoundError(FileNotFoundError):  # type: ignore[no-redef]
        def __init__(self, message: str, status: int | None = None, filename: str | None = None) -> None:
            super().__init__(message)


class LocalAfc:
    """Expose a local directory tree as if it were an AFC filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise NotADirectoryError(f"not a directory: {self.root}")
        self._handles: dict[int, Any] = {}
        self._next_handle = 0
        self._terminated = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------
    async def wait_terminated(self) -> None:
        await self._terminated.wait()

    def terminate(self) -> None:
        """Simulate the device disconnecting."""
        self._terminated.set()

    # -- path helpers ------------------------------------------------------
    def _p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def _missing(self, path: str) -> AfcFileNotFoundError:
        return AfcFileNotFoundError(f"No such file or directory: {path}", 8, path)

    async def exists(self, path: str) -> bool:
        return self._p(path).exists()

    async def listdir(self, path: str) -> list[str]:
        try:
            return [entry.name for entry in self._p(path).iterdir()]
        except FileNotFoundError:
            raise self._missing(path) from None

    async def isdir(self, path: str) -> bool:
        return self._p(path).is_dir()

    async def os_stat(self, path: str) -> os.stat_result:
        try:
            return os.stat(self._p(path))
        except FileNotFoundError:
            raise self._missing(path) from None

    async def stat(self, path: str) -> dict[str, Any]:
        try:
            info = os.stat(self._p(path))
        except FileNotFoundError:
            raise self._missing(path) from None
        ifmt = "S_IFDIR" if stat_module.S_ISDIR(info.st_mode) else "S_IFREG"
        return {
            "st_size": info.st_size,
            "st_ifmt": ifmt,
            "st_nlink": 1,
            "st_blocks": (info.st_size + 511) // 512,
            "st_mtime": datetime.fromtimestamp(info.st_mtime, tz=timezone.utc),
            "st_birthtime": datetime.fromtimestamp(info.st_birthtime, tz=timezone.utc),
        }

    # -- file handles ------------------------------------------------------
    async def fopen(self, path: str, mode: str = "r") -> int:
        handle = self._next_handle
        self._next_handle += 1
        try:
            self._handles[handle] = open(self._p(path), "wb" if "w" in mode else "rb")
        except FileNotFoundError:
            raise self._missing(path) from None
        return handle

    async def fread(self, handle: int, size: int) -> bytes:
        return self._handles[handle].read(size)

    async def fwrite(self, handle: int, data: bytes) -> int:
        return self._handles[handle].write(data)

    async def fseek(self, handle: int, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._handles[handle].seek(offset, whence)

    async def fclose(self, handle: int) -> None:
        self._handles.pop(handle).close()

    # -- mutation ----------------------------------------------------------
    async def rm(self, path: str, force: bool = False) -> list[str]:
        target = self._p(path)
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        return [path]

    async def makedirs(self, path: str) -> None:
        self._p(path).mkdir(parents=True, exist_ok=True)

    async def rename(self, src: str, dst: str) -> None:
        self._p(src).rename(self._p(dst))

    # -- mirror backend helpers -------------------------------------------
    async def walk(self, dirname: str):
        base = self._p(dirname)
        for root, dirs, files in os.walk(base):
            rel = Path(root).relative_to(base)
            dev = dirname if str(rel) == "." else posixpath.join(dirname, rel.as_posix())
            yield dev, dirs, files

    async def pull(self, relative_src: str, dst: str, progress_bar: bool = True, **_: Any) -> None:
        shutil.copy2(self._p(relative_src), dst)
