"""Device discovery and lockdown connection helpers.

All access goes through Apple's ``usbmuxd`` (``/var/run/usbmuxd`` on macOS), so
no third-party daemon is required — pymobiledevice3 speaks the native protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from pymobiledevice3.usbmux import MuxDevice, list_devices, select_device

from .errors import NoDeviceError

# Keys we surface from lockdownd's AllValues dictionary.
_INFO_KEYS = {
    "name": "DeviceName",
    "product_type": "ProductType",
    "product_version": "ProductVersion",
    "build_version": "BuildVersion",
    "model": "ModelNumber",
    "region": "RegionInfo",
}


@dataclass
class DeviceInfo:
    """A concise, human-friendly summary of a connected device."""

    udid: str
    name: str = ""
    product_type: str = ""
    product_version: str = ""
    build_version: str = ""
    connection_type: str = ""
    serial: str = ""

    @property
    def label(self) -> str:
        return self.name or self.product_type or self.udid


async def list_connected(udid: Optional[str] = None) -> list[MuxDevice]:
    """Return the connected devices, optionally filtered by UDID/serial."""
    devices = await list_devices()
    if udid:
        devices = [d for d in devices if d.matches_udid(udid)]
    return devices


async def wait_for_device(
    udid: Optional[str] = None,
    *,
    timeout: float = 0.0,
    interval: float = 1.0,
) -> MuxDevice:
    """Block until a device is available and return it.

    :param udid: Only accept this UDID/serial (``None`` accepts any device).
    :param timeout: Give up after this many seconds (``0`` waits forever).
    :param interval: Poll interval in seconds.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        device = await select_device(udid=udid)
        if device is not None:
            return device
        if timeout and (loop.time() - started) >= timeout:
            raise NoDeviceError(f"等待设备超时（{timeout:g}s）：未发现连接中的 iOS 设备")
        await asyncio.sleep(interval)


async def connect_lockdown(
    udid: Optional[str] = None,
    *,
    autopair: bool = True,
    wait: bool = False,
    timeout: float = 0.0,
) -> LockdownClient:
    """Open a lockdownd connection to the requested (or first USB) device.

    :param udid: Target UDID/serial, or ``None`` for the first USB device.
    :param autopair: Perform the trust/pair handshake when needed.
    :param wait: Wait for a device to appear instead of failing immediately.
    :param timeout: Timeout for :func:`wait_for_device` (``0`` = forever).
    """
    if wait:
        device = await wait_for_device(udid, timeout=timeout)
        serial = device.serial
    else:
        device = await select_device(udid=udid)
        if device is None:
            raise NoDeviceError(
                "未发现 iOS 设备。请用数据线连接 iPhone/iPad，并在设备上点击“信任此电脑”；"
                "或使用 --wait 等待设备接入。"
            )
        serial = device.serial

    try:
        return await create_using_usbmux(serial=serial, autopair=autopair)
    except Exception as exc:  # noqa: BLE001 - re-raised with a friendlier message
        raise NoDeviceError(
            f"连接设备失败：{exc}\n请确认设备已解锁并已信任本电脑。"
        ) from exc


async def read_info(lockdown: LockdownClient, *, connection_type: str = "") -> DeviceInfo:
    """Read device metadata from a lockdown client."""
    values = getattr(lockdown, "all_values", None) or {}
    if not values:
        try:
            values = await lockdown.get_value()
            lockdown.all_values = values  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - metadata is best-effort
            values = {}

    info = DeviceInfo(
        udid=getattr(lockdown, "udid", "") or "",
        connection_type=connection_type,
        serial=getattr(lockdown, "identifier", "") or "",
    )
    for attr, key in _INFO_KEYS.items():
        value = values.get(key)
        if value:
            setattr(info, attr, str(value))
    return info


async def close_lockdown(lockdown: Optional[LockdownClient]) -> None:
    """Close a lockdown client, swallowing teardown errors.

    Closing is important: pymobiledevice3 speaks TLS over usbmuxd, and if the
    transport is still open when the asyncio loop shuts down, the SSL layer
    later tries to write to a dead socket and prints
    ``Fatal error on SSL transport ... Event loop is closed``.
    """
    if lockdown is None:
        return
    with contextlib.suppress(Exception):
        await lockdown.close()


@asynccontextmanager
async def open_lockdown(
    udid: Optional[str] = None,
    *,
    autopair: bool = True,
    wait: bool = False,
    timeout: float = 0.0,
) -> AsyncIterator[LockdownClient]:
    """Async context manager that connects and *always* closes the client.

    Usage::

        async with open_lockdown(udid, wait=True) as lockdown:
            ...
    """
    client = await connect_lockdown(udid, autopair=autopair, wait=wait, timeout=timeout)
    try:
        yield client
    finally:
        await close_lockdown(client)
