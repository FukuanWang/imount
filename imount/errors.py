"""Typed exceptions used across imount."""

from __future__ import annotations


class ImountError(Exception):
    """Base class for all expected, user-facing imount errors."""


class NoDeviceError(ImountError):
    """No (matching) iOS device is currently connected."""


class MountError(ImountError):
    """Mounting or unmounting the WebDAV volume failed."""


class UnsupportedHostError(ImountError):
    """The host is missing a required capability (e.g. ``mount_webdav``)."""


class AfcPathError(ImountError):
    """A path on the device could not be found or accessed."""
