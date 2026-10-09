"""imount - Mount an iOS device's media (DCIM photos & videos) on macOS.

The tool talks to the device through Apple's own ``usbmuxd`` (already running on
macOS) using :mod:`pymobiledevice3`, exposes the AFC filesystem over a local
WebDAV server, and then asks macOS to mount that server at a directory you
choose.  Because macOS mounts WebDAV natively (``mount_webdav``) there is **no
kernel extension / macFUSE required**.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
