"""Command line interface for imount (built with Typer)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from pymobiledevice3.services.afc import AfcService

from . import __version__
from .backends import mirror as mirror_backend
from .backends import webdav as webdav_backend
from .device import list_connected, open_lockdown, read_info
from .errors import AfcPathError, ImountError
from .util import default_volume_name, human_size, is_macos, which

app = typer.Typer(
    name="imount",
    help="把 iOS 设备的资料（照片/视频/媒体文件）挂载或同步到 Mac 指定目录。",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# AFC 的根对应设备上的 /var/mobile/Media；“/”即整个媒体库（DCIM、PhotoData 等）。
DEFAULT_AFC_PATH = "/"
# 同步默认仍以 DCIM 为限，避免一次拉取整个媒体库。
DEFAULT_SYNC_PATH = "/DCIM"


def _fail(message: str, code: int = 1) -> None:
    typer.secho(f"错误：{message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _version_callback(value: bool) -> bool:
    if value:
        typer.echo(f"imount {__version__}")
        raise typer.Exit()
    return value


def _run(coro) -> None:
    """Run an async command, mapping expected errors to friendly exits."""
    try:
        asyncio.run(coro)
    except ImountError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        typer.echo("已取消。")


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="显示版本并退出。",
    ),
) -> None:
    """imount：把 iOS 设备的资料挂载或同步到 Mac。"""


# --------------------------------------------------------------------------- #
# devices / info / doctor
# --------------------------------------------------------------------------- #
@app.command("devices")
def devices(json_output: bool = typer.Option(False, "--json", help="以 JSON 输出。")) -> None:
    """列出已连接的 iOS 设备。"""

    async def _list() -> None:
        mux_devices = await list_connected()
        if not mux_devices:
            if json_output:
                typer.echo("[]")
            else:
                typer.echo("未发现设备。请连接 iPhone/iPad 并在设备上点击“信任此电脑”。")
            return

        records = []
        for mux in mux_devices:
            record = {"udid": mux.serial, "connection_type": mux.connection_type, "name": ""}
            try:
                async with open_lockdown(udid=mux.serial, autopair=False) as lockdown:
                    info = await read_info(lockdown, connection_type=mux.connection_type)
                record.update(
                    {
                        "udid": info.udid or mux.serial,
                        "name": info.name,
                        "product_type": info.product_type,
                        "product_version": info.product_version,
                    }
                )
            except Exception:  # noqa: BLE001 - metadata is best effort
                pass
            records.append(record)

        if json_output:
            typer.echo(json.dumps(records, ensure_ascii=False, indent=2))
            return
        for index, record in enumerate(records, 1):
            name = record.get("name") or "(未解锁/未信任)"
            model = record.get("product_type") or "?"
            version = record.get("product_version") or "?"
            typer.echo(f"[{index}] {name}  {model}  iOS {version}")
            typer.echo(f"    UDID: {record['udid']}  连接: {record['connection_type']}")

    _run(_list())


@app.command("info")
def info(
    device: Optional[str] = typer.Option(None, "--device", "-d", help="目标设备 UDID/序列号。"),
    wait: bool = typer.Option(False, "--wait", "-w", help="等待设备接入。"),
) -> None:
    """显示目标设备的详细信息。"""

    async def _info() -> None:
        async with open_lockdown(device, wait=wait) as lockdown:
            dev_info = await read_info(lockdown)
        typer.echo(f"名称    : {dev_info.name}")
        typer.echo(f"型号    : {dev_info.product_type}")
        typer.echo(f"系统    : iOS {dev_info.product_version} ({dev_info.build_version})")
        typer.echo(f"UDID    : {dev_info.udid}")

    _run(_info())


@app.command("doctor")
def doctor() -> None:
    """检查运行环境（usbmuxd、mount_webdav、设备等）。"""

    async def _doctor() -> None:
        typer.echo(f"imount {__version__}")
        typer.echo(f"Python  : {sys.version.split()[0]}")
        typer.echo(f"系统    : {'macOS' if is_macos() else sys.platform}")

        usbmuxd = Path("/var/run/usbmuxd")
        typer.echo(f"usbmuxd : {'存在' if usbmuxd.exists() else '未找到 (/var/run/usbmuxd)'}")

        mount_webdav = which("mount_webdav")
        typer.echo(f"mount_webdav : {mount_webdav or '未找到'}")

        try:
            import asgi_webdav  # noqa: F401

            typer.echo("asgiwebdav    : 可用")
        except ImportError:
            typer.echo("asgiwebdav    : 缺失（pip install asgiwebdav）")

        try:
            mux_devices = await list_connected()
            typer.echo(f"已连接设备    : {len(mux_devices)} 台")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"设备检测失败  : {exc}")

    _run(_doctor())


# --------------------------------------------------------------------------- #
# mount / umount / serve
# --------------------------------------------------------------------------- #
@app.command("mount")
def mount(
    mount_point: Path = typer.Argument(..., help="本地挂载目录（不存在会自动创建）。"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="目标设备 UDID/序列号。"),
    afc_path: str = typer.Option(
        DEFAULT_AFC_PATH,
        "--afc-path",
        "-p",
        help="要挂载的设备内路径；默认 /（整个媒体库 /var/mobile/Media，含 DCIM）。",
    ),
    readonly: bool = typer.Option(
        True, "--readonly/--rw", help="只读挂载（推荐，避免误删/损坏设备资料）。"
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="WebDAV 监听地址。"),
    port: int = typer.Option(0, "--port", help="WebDAV 监听端口（0 自动选择）。"),
    volume_name: Optional[str] = typer.Option(None, "--volume-name", "-n", help="Finder 中显示的卷名。"),
    reveal: bool = typer.Option(False, "--reveal", help="挂载后在 Finder 中打开。"),
    wait: bool = typer.Option(False, "--wait", "-w", help="等待设备接入后再挂载。"),
    timeout: float = typer.Option(0.0, "--timeout", help="等待设备超时秒数（0 表示不限）。"),
) -> None:
    """把设备目录挂载到本地指定目录（前台运行，Ctrl-C 卸载）。"""

    async def _mount() -> None:
        if not webdav_backend.webdav_available():
            _fail(
                "当前环境不支持 WebDAV 挂载（需要 macOS + /sbin/mount_webdav）。"
            )
        async with open_lockdown(device, wait=wait, timeout=timeout) as lockdown:
            dev_info = await read_info(lockdown)
            name = volume_name or default_volume_name(dev_info.name, afc_path)
            async with AfcService(lockdown=lockdown) as afc:
                if not await afc.exists(afc_path):
                    raise AfcPathError(f"设备上不存在路径：{afc_path}")
                await webdav_backend.run_mount_session(
                    afc,
                    afc_path=afc_path,
                    mount_point=mount_point,
                    host=host,
                    port=port,
                    readonly=readonly,
                    volume_name=name,
                    reveal=reveal,
                )

    _run(_mount())


@app.command("demo")
def demo(
    source: Path = typer.Argument(..., help="本地目录，模拟设备的 AFC 根。"),
    mount_point: Path = typer.Argument(..., help="本地挂载点（不存在会自动创建）。"),
    afc_path: str = typer.Option("/", "--afc-path", "-p", help="在模拟 AFC 中要挂载的子路径。"),
    readonly: bool = typer.Option(True, "--readonly/--rw", help="只读挂载。"),
    reveal: bool = typer.Option(False, "--reveal", help="挂载后在 Finder 中打开。"),
) -> None:
    """用本地目录模拟 iOS 设备，验证完整挂载流程（无需真机）。"""

    async def _demo() -> None:
        from .local_afc import LocalAfc

        if not webdav_backend.webdav_available():
            _fail("当前环境不支持 WebDAV 挂载（需要 macOS + /sbin/mount_webdav）。")
        afc = LocalAfc(source)
        if not await afc.exists(afc_path):
            raise AfcPathError(f"本地目录中不存在路径：{afc_path}")
        await webdav_backend.run_mount_session(
            afc,
            afc_path=afc_path,
            mount_point=mount_point,
            readonly=readonly,
            volume_name=f"imount-demo-{source.name}",
            reveal=reveal,
        )

    _run(_demo())


@app.command("umount")
def umount(
    mount_point: Path = typer.Argument(..., help="要卸载的挂载目录。"),
    force: bool = typer.Option(True, "--force/--no-force", help="失败时强制卸载。"),
) -> None:
    """卸载一个 WebDAV 挂载目录。"""

    async def _umount() -> None:
        ok = await webdav_backend.unmount_webdav(mount_point, force=force)
        if ok:
            typer.echo(f"已卸载：{mount_point}")
        else:
            _fail(f"卸载失败：{mount_point}")

    _run(_umount())


@app.command("serve")
def serve(
    afc_path: str = typer.Option(DEFAULT_AFC_PATH, "--afc-path", "-p", help="要暴露的设备内路径。"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="目标设备 UDID/序列号。"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址。"),
    port: int = typer.Option(0, "--port", help="监听端口（0 自动选择）。"),
    readonly: bool = typer.Option(True, "--readonly/--rw", help="只读服务。"),
    wait: bool = typer.Option(False, "--wait", "-w", help="等待设备接入。"),
) -> None:
    """只启动 WebDAV 服务并打印地址（不自动挂载）。"""

    async def _serve() -> None:
        async with open_lockdown(device, wait=wait) as lockdown:
            async with AfcService(lockdown=lockdown) as afc:
                if not await afc.exists(afc_path):
                    raise AfcPathError(f"设备上不存在路径：{afc_path}")
                await webdav_backend.run_serve_session(
                    afc, afc_path=afc_path, host=host, port=port, readonly=readonly
                )

    _run(_serve())


# --------------------------------------------------------------------------- #
# ls / sync
# --------------------------------------------------------------------------- #
@app.command("ls")
def ls(
    afc_path: str = typer.Argument(DEFAULT_AFC_PATH, help="设备内路径。"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="目标设备 UDID/序列号。"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="递归列出。"),
    long: bool = typer.Option(False, "--long", "-l", help="显示大小。"),
) -> None:
    """列出设备上的文件。"""

    async def _ls() -> None:
        async with open_lockdown(device) as lockdown:
            async with AfcService(lockdown=lockdown) as afc:
                if not await afc.exists(afc_path):
                    raise AfcPathError(f"设备上不存在路径：{afc_path}")
                async for path in afc.dirlist(afc_path, -1 if recursive else 1):
                    if long and path != afc_path:
                        try:
                            stat = await afc.stat(path)
                            size = human_size(int(stat.get("st_size", 0) or 0))
                            typer.echo(f"{size:>10}  {path}")
                            continue
                        except Exception:  # noqa: BLE001
                            pass
                    typer.echo(path)

    _run(_ls())


@app.command("sync")
def sync(
    dest: Path = typer.Argument(..., help="本地目标目录。"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="目标设备 UDID/序列号。"),
    afc_path: str = typer.Option(DEFAULT_SYNC_PATH, "--afc-path", "-p", help="要同步的设备内路径（默认 /DCIM）。"),
    delete: bool = typer.Option(False, "--delete", help="删除本地多余文件，使目标与设备一致。"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅显示将要执行的操作。"),
    include_hidden: bool = typer.Option(True, "--hidden/--no-hidden", help="是否包含隐藏文件。"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="不逐个打印文件。"),
) -> None:
    """把设备目录镜像（增量复制）到本地目录（不挂载）。"""

    async def _sync() -> None:
        async with open_lockdown(device) as lockdown:
            async with AfcService(lockdown=lockdown) as afc:
                def on_file(action: str, path: str) -> None:
                    if quiet:
                        return
                    mark = {"copy": "+", "error": "!"}.get(action, " ")
                    typer.echo(f"  {mark} {path}")

                typer.echo(f"同步 {afc_path} -> {dest} {'(dry-run) ' if dry_run else ''}…")
                stats = await mirror_backend.mirror(
                    afc,
                    afc_path,
                    dest,
                    delete=delete,
                    dry_run=dry_run,
                    include_hidden=include_hidden,
                    on_file=on_file,
                )
                typer.echo(stats.summary())

    _run(_sync())


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except ImountError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
