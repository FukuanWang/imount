"""Small OS helpers shared by the CLI and the backends."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path


def is_macos() -> bool:
    """Return ``True`` when running on macOS (Darwin)."""
    return sys.platform == "darwin"


def which(name: str) -> str | None:
    """Locate an executable, also searching ``/sbin`` and ``/usr/sbin``.

    ``mount_webdav`` lives in ``/sbin`` which is not always on ``PATH`` when
    imount is started from a GUI/launchd context.
    """
    found = shutil.which(name)
    if found:
        return found
    for directory in ("/sbin", "/usr/sbin", "/usr/bin", "/bin"):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


async def run_command(argv: list[str], *, check: bool = False) -> tuple[int, str]:
    """Run a command, returning ``(returncode, combined_output)``.

    Output is captured through an anonymous temporary file rather than a pipe.
    This matters for ``mount_webdav``: it forks a long-lived ``webdavfs_agent``
    helper that inherits our stdio.  With a pipe, ``communicate()`` would block
    forever waiting for EOF that only happens when the volume is unmounted.

    The command is executed without a shell and never raises on a non-zero exit
    unless ``check`` is set.
    """
    with tempfile.TemporaryFile() as sink:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=sink,
            stderr=asyncio.subprocess.STDOUT,
        )
        code = await proc.wait()
        sink.seek(0)
        text = sink.read().decode(errors="replace")
    if check and code != 0:
        raise RuntimeError(f"{argv[0]} failed ({code}): {text.strip()}")
    return code, text


def is_empty_dir(path: Path) -> bool:
    """Return ``True`` when ``path`` exists, is a directory and has no entries."""
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def normalize_mount_path(path: str | os.PathLike[str]) -> str:
    """Return a symlink-normalized form of ``path`` *without* touching it.

    ``os.path.realpath`` must not be called on the mount point itself: while a
    WebDAV volume is mounted, stat-ing it blocks the process that runs the
    WebDAV server (see :func:`is_mounted`).  Resolving only the parent directory
    is safe and still collapses ``/tmp`` -> ``/private/tmp`` style differences.
    """
    raw = os.path.abspath(os.fspath(path))
    if raw == os.path.sep:
        return raw
    stripped = raw.rstrip(os.path.sep)
    parent = os.path.dirname(stripped) or os.path.sep
    return os.path.join(os.path.realpath(parent), os.path.basename(stripped))


async def list_mount_points() -> list[str]:
    """Return the mount points from the kernel mount table (via ``mount``)."""
    _code, output = await run_command(["mount"])
    points: list[str] = []
    for line in output.splitlines():
        if " on " not in line:
            continue
        rest = line.split(" on ", 1)[1]
        point = rest.rsplit(" (", 1)[0].strip()
        if point:
            points.append(point)
    return points


async def is_mounted(path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` is a mount point.

    Implemented by reading the kernel mount table rather than calling
    ``os.path.ismount``: the latter stats the path, which deadlocks when the
    caller is also the process serving the mounted WebDAV volume.
    """
    target = normalize_mount_path(path)
    return any(normalize_mount_path(point) == target for point in await list_mount_points())


def human_size(num: float) -> str:
    """Format a byte count using binary (KiB/MiB/GiB) units."""
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(num) < step or unit == "PiB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} PiB"


def default_volume_name(device_name: str | None = None, afc_path: str = "/DCIM") -> str:
    """Build a friendly Finder volume name, e.g. ``iPhone-DCIM``."""
    base = (device_name or "iOS Device").strip() or "iOS Device"
    base = "".join(ch for ch in base if ch.isalnum() or ch in " ._-").strip() or "iOS Device"
    leaf = afc_path.strip("/").split("/")[-1] or "Media"
    return f"{base}-{leaf}"
