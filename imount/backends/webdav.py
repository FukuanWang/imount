"""WebDAV mount backend.

How it works
------------
1. An open :class:`pymobiledevice3.services.afc.AfcService` is wrapped in a
   local WebDAV server (ASGIWebDAV, provided by pymobiledevice3) bound to
   loopback.
2. macOS' built-in ``mount_webdav`` mounts that URL at a directory chosen by the
   user.  The result is a real mounted volume that Finder, Preview, QuickTime,
   ``cp``, ``rsync`` … can browse directly, **without macFUSE or any kernel
   extension**.
3. The process stays in the foreground and keeps the server alive.  It
   unmounts automatically when the device disconnects, when the mount is
   removed externally, or on ``Ctrl-C``.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..errors import MountError, UnsupportedHostError
from ..util import is_mounted, run_command, which

MOUNT_WEBDAV = "mount_webdav"
UNMOUNT_POLL_INTERVAL = 1.0


def webdav_available() -> bool:
    """Whether this host can natively mount a WebDAV volume."""
    return sys.platform == "darwin" and which(MOUNT_WEBDAV) is not None


def _require_webdav() -> None:
    if sys.platform != "darwin":
        raise UnsupportedHostError("WebDAV 挂载后端目前仅支持 macOS。")
    if which(MOUNT_WEBDAV) is None:
        raise UnsupportedHostError(
            "未找到 mount_webdav，无法挂载 WebDAV 卷。macOS 自带该命令，请检查 /sbin 是否可用。"
        )


def _serve_afc_webdav() -> Callable[..., Any]:
    try:
        from pymobiledevice3.services.webdav import serve_afc_webdav
    except ImportError as exc:  # pragma: no cover - depends on interpreter version
        raise UnsupportedHostError(
            "WebDAV 功能需要 Python >= 3.10 以及 asgiwebdav/uvicorn 依赖。"
        ) from exc
    return serve_afc_webdav


async def serve_afc(
    afc: Any,
    *,
    path: str = "/",
    host: str = "127.0.0.1",
    port: int = 0,
    readonly: bool = True,
) -> Any:
    """Start the in-process WebDAV server for an open AFC service."""
    return await _serve_afc_webdav()(afc, path=path, host=host, port=port, readonly=readonly)


async def mount_webdav(
    url: str,
    mount_point: Path,
    *,
    volume_name: Optional[str] = None,
    readonly: bool = False,
    wait: float = 10.0,
) -> None:
    """Mount ``url`` at ``mount_point`` using macOS' ``mount_webdav``."""
    _require_webdav()
    mount_point = mount_point.expanduser()
    # Check the mount table before mkdir: mkdir(exist_ok=True) stats the path,
    # which would deadlock if a volume is already mounted there.
    if await is_mounted(mount_point):
        raise MountError(f"挂载点已经是挂载状态：{mount_point}")
    mount_point.mkdir(parents=True, exist_ok=True)

    argv = [MOUNT_WEBDAV, "-S"]
    if volume_name:
        argv += ["-v", volume_name]
    if readonly:
        argv += ["-o", "rdonly"]
    argv += [url, str(mount_point)]

    code, output = await run_command(argv)
    if code != 0:
        raise MountError(f"mount_webdav 失败（退出码 {code}）：{output.strip()}")

    # ``mount_webdav`` returns before the volume is necessarily ready; poll the
    # kernel mount table (never stat the mount point - see util.is_mounted).
    deadline = asyncio.get_running_loop().time() + max(wait, 0)
    while asyncio.get_running_loop().time() < deadline:
        if await is_mounted(mount_point):
            return
        await asyncio.sleep(0.1)
    if not await is_mounted(mount_point):
        raise MountError(f"挂载命令已执行，但 {mount_point} 未成为挂载点。")


async def unmount_webdav(mount_point: Path, *, force: bool = True) -> bool:
    """Unmount a WebDAV volume.  Returns ``True`` when it is no longer mounted."""
    mount_point = mount_point.expanduser()
    if not await is_mounted(mount_point):
        return True

    attempts = [["diskutil", "unmount", str(mount_point)], ["umount", str(mount_point)]]
    if force:
        attempts.append(["diskutil", "unmount", "force", str(mount_point)])

    for argv in attempts:
        await run_command(argv)
        if not await is_mounted(mount_point):
            return True
    return not await is_mounted(mount_point)


async def reveal_in_finder(path: Path) -> None:
    """Best-effort reveal of ``path`` in the Finder."""
    with contextlib.suppress(OSError):
        await run_command(["open", str(path)])


async def _wait_for_stop(afc: Any, server: Any, mount_point: Optional[Path]) -> str:
    """Block until the session should end and return the trigger name.

    Triggers: ``signal`` (Ctrl-C/SIGTERM), ``device`` (device unplugged),
    ``unmount`` (volume removed in Finder), ``server`` (WebDAV server exited).
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed: list[int] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)

    async def watch_unmount() -> str:
        while True:
            await asyncio.sleep(UNMOUNT_POLL_INTERVAL)
            if not await is_mounted(mount_point):  # type: ignore[arg-type]
                return "unmount"

    tasks: dict[asyncio.Task, str] = {
        loop.create_task(stop.wait()): "signal",
        loop.create_task(afc.wait_terminated()): "device",
    }
    if mount_point is not None:
        tasks[loop.create_task(watch_unmount())] = "unmount"
    server_task = getattr(server, "_task", None)
    if server_task is not None:
        tasks[server_task] = "server"

    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            name = tasks[task]
            if name == "device":
                return "device"
            if name == "server":
                return "server"
            if name == "unmount":
                return "unmount"
        return "signal"
    finally:
        # Cancel the waiter tasks we created, but never the uvicorn server task:
        # ``server.stop()`` owns it and expects to await it gracefully.
        for task, name in tasks.items():
            if name != "server" and not task.done():
                task.cancel()
        waiters = [t for t, name in tasks.items() if name != "server"]
        with contextlib.suppress(Exception):
            await asyncio.gather(*waiters, return_exceptions=True)
        for sig in installed:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(sig)


async def run_mount_session(
    afc: Any,
    *,
    afc_path: str,
    mount_point: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    readonly: bool = True,
    volume_name: Optional[str] = None,
    reveal: bool = False,
    announce: bool = True,
) -> None:
    """Serve ``afc`` over WebDAV and mount it until the session ends.

    This function blocks for the lifetime of the mount and always cleans up
    (unmount + server shutdown) before returning.
    """
    _require_webdav()
    mount_point = Path(mount_point).expanduser()
    # Check the mount table before mkdir (see mount_webdav).
    if await is_mounted(mount_point):
        raise MountError(f"挂载点已经是挂载状态：{mount_point}")
    mount_point.mkdir(parents=True, exist_ok=True)

    server = await serve_afc(afc, path=afc_path, host=host, port=port, readonly=readonly)
    mounted = False
    try:
        await mount_webdav(server.url, mount_point, volume_name=volume_name, readonly=readonly)
        mounted = True
        if announce:
            mode = "只读" if readonly else "读写"
            print(f"✅ 已挂载：{mount_point}")
            print(f"   设备路径 : {afc_path}")
            print(f"   WebDAV   : {server.url}")
            print(f"   挂载模式 : {mode}")
            print("   按 Ctrl-C 卸载并退出。")
        if reveal:
            await reveal_in_finder(mount_point)

        reason = await _wait_for_stop(afc, server, mount_point)
        messages = {
            "device": "设备已断开，正在卸载…",
            "unmount": "卷已被卸载，正在停止服务…",
            "server": "WebDAV 服务已停止，正在卸载…",
            "signal": "收到中断信号，正在卸载…",
        }
        if announce:
            print(messages.get(reason, "正在退出…"))
    finally:
        if mounted:
            await unmount_webdav(mount_point)
        await server.stop()
        if announce:
            print("已卸载。")


async def run_serve_session(
    afc: Any,
    *,
    afc_path: str,
    host: str = "127.0.0.1",
    port: int = 0,
    readonly: bool = True,
) -> None:
    """Serve ``afc`` over WebDAV without mounting; print the URL and block."""
    _require_webdav()
    server = await serve_afc(afc, path=afc_path, host=host, port=port, readonly=readonly)
    try:
        mode = "只读" if readonly else "读写"
        print(f"WebDAV 服务已启动（{mode}）：{server.url}")
        print(f"设备路径：{afc_path}")
        print(f'可在 Finder 中“连接服务器”，或执行：mount_webdav -S {server.url} <挂载点>')
        print("按 Ctrl-C 停止。")
        await _wait_for_stop(afc, server, None)
    finally:
        await server.stop()
        print("服务已停止。")
