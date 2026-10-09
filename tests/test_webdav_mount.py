"""End-to-end tests for the WebDAV mount lifecycle (requires macOS + mount_webdav).

Important: the WebDAV server runs *inside* this process.  Any filesystem call on
the mounted volume from this process would deadlock (the call blocks the event
loop that must answer ``webdavfs``'s HTTP requests), so all inspection of the
mounted volume is done through child processes.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from imount.backends import webdav
from imount.util import is_mounted

pytestmark = pytest.mark.skipif(
    not webdav.webdav_available(),
    reason="需要 macOS 且 /sbin/mount_webdav 可用",
)


async def _run(argv: list[str]) -> tuple[int, bytes]:
    """Run a helper command in a *separate* process and return (rc, raw output)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out


async def _wait_mounted(path: Path, timeout: float = 20.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await is_mounted(path):
            return True
        await asyncio.sleep(0.1)
    return await is_mounted(path)


async def _force_cleanup(mount_point: Path, task: asyncio.Task) -> None:
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if await is_mounted(mount_point):
        await webdav.unmount_webdav(mount_point, force=True)


async def test_run_mount_session_readonly(local_afc, tmp_path: Path) -> None:
    """Serving the fake AFC over WebDAV and mounting it exposes the files."""
    mount_point = tmp_path / "mnt"
    task = asyncio.create_task(
        webdav.run_mount_session(
            local_afc,
            afc_path="/",
            mount_point=mount_point,
            readonly=True,
            announce=False,
        )
    )
    try:
        assert await _wait_mounted(mount_point), "挂载未成功"

        rc, out = await _run(["ls", str(mount_point / "100APPLE")])
        assert rc == 0, out.decode(errors="replace")
        assert sorted(out.decode().split()) == ["IMG_0001.JPG", "IMG_0002.JPG"]

        rc, out = await _run(["cat", str(mount_point / "100APPLE" / "IMG_0001.JPG")])
        assert rc == 0
        assert out == b"\xff\xd8" + b"a" * 2046

        rc, out = await _run(["ls", str(mount_point / "101APPLE")])
        assert sorted(out.decode().split()) == ["IMG_0003.MOV"]

        # A device disconnect should unmount and stop the server.
        local_afc.terminate()
        await asyncio.wait_for(task, timeout=30)
    finally:
        await _force_cleanup(mount_point, task)

    assert not await is_mounted(mount_point)


async def test_run_mount_session_subpath(local_afc, tmp_path: Path) -> None:
    """Mounting a sub-path exposes only that directory."""
    mount_point = tmp_path / "mnt_sub"
    task = asyncio.create_task(
        webdav.run_mount_session(
            local_afc,
            afc_path="/100APPLE",
            mount_point=mount_point,
            readonly=True,
            announce=False,
        )
    )
    try:
        assert await _wait_mounted(mount_point)
        rc, out = await _run(["ls", str(mount_point)])
        assert rc == 0, out.decode(errors="replace")
        assert sorted(out.decode().split()) == ["IMG_0001.JPG", "IMG_0002.JPG"]
        local_afc.terminate()
        await asyncio.wait_for(task, timeout=30)
    finally:
        await _force_cleanup(mount_point, task)


async def test_unmount_webdav_idempotent(tmp_path: Path) -> None:
    """Unmounting a non-mounted directory is a no-op that reports success."""
    plain = tmp_path / "not_mounted"
    plain.mkdir()
    assert await webdav.unmount_webdav(plain, force=True) is True
