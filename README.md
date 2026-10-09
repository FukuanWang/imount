# imount

> 把 iPhone / iPad 上的资料（照片、视频、整个 Media 媒体库）**挂载**成 macOS 上的一个真实磁盘卷 ——
> 一条命令、指定目录、**不需要 macFUSE，也不需要任何内核扩展**。

```bash
imount mount ~/iPhoneMedia              # 默认挂载整个媒体库（/var/mobile/Media）
imount mount ~/iPhonePhotos -p /DCIM    # 只挂载相机胶卷
```

之后在 Finder、预览、QuickTime、`cp`、`rsync`、任何编辑器里都能像普通文件夹一样
浏览和读取设备上的原始文件。

```text
~/iPhoneMedia/            # 等价于设备上的 /var/mobile/Media
├── DCIM/                 # 相机胶卷原始照片 / 视频
│   ├── 100APPLE/
│   │   ├── IMG_0002.JPG  # 直接读取，无需先导入
│   │   └── IMG_0003.MOV
│   └── ...
├── PhotoData/            # 照片库数据库与衍生资源
├── Purchases/
└── ...
```

---

## ✨ 特性

- **默认挂载整个媒体库**：`imount mount <目录>` 挂载 AFC 根（设备上的 `/var/mobile/Media`），
  用 `-p /DCIM` 可只看相机胶卷。
- **真实挂载卷**：不是同步/拷贝，是 macOS 文件系统里真正的一个挂载点。
- **零内核扩展**：利用 macOS 自带的 `mount_webdav`，无需 macFUSE、无需重启、无需改安全设置。
- **零额外守护进程**：直接使用 macOS 原生的 `usbmuxd` 与设备通信。
- **默认只读**：避免误删/损坏设备照片库；需要时 `--rw`。
- **自动清理**：`Ctrl-C`、Finder 推出卷、拔掉设备都会自动卸载。
- **无需 Xcode / 开发者模式 / Developer Disk Image**：AFC 是普通服务，信任设备即可。
- **附带增量同步** `imount sync`，以及无真机自检 `imount demo`。

---

## 🚀 一键安装

```bash
cd imount
./install.sh
```

安装脚本会自动完成依赖检查与安装：

1. 检查是否为 macOS，以及系统自带的 `/sbin/mount_webdav`；
2. 查找 Python ≥ 3.10（缺失会提示，不静默安装）；
3. 确保 `pipx` 可用（优先 Homebrew，其次 `pip --user`）；
4. 用 `pipx` 把 imount 安装到独立环境（**不污染系统 Python**）；
5. 把 `imount` 链接到 `/usr/local/bin`（仅此步需要 sudo 时会提示密码）；
6. 运行 `imount doctor` 做最终自检。

安装完成后：

```bash
imount -h          # 查看全部用法
imount doctor      # 环境自检
```

卸载：

```bash
./install.sh --uninstall
```

### 环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | macOS（已在 macOS 26 / Apple Silicon 验证） |
| Python | 3.10 及以上 |
| 设备 | iPhone / iPad，数据线连接并在设备上点「信任此电脑」 |
| 其它 | 无。`mount_webdav` 为系统自带；**无需 macFUSE / Xcode** |

> 手动安装（不使用脚本）：
> ```bash
> pipx install --python python3 .     # 或：pip install .
> ```

---

## 📖 用法

### 1. 挂载（核心）

```bash
# 挂载整个媒体库（默认：AFC 根 = 设备上的 /var/mobile/Media）
imount mount ~/iPhoneMedia

# 只挂载相机胶卷 DCIM
imount mount ~/iPhonePhotos -p /DCIM

# 指定设备；读写；挂载后在 Finder 打开
imount mount ~/iPhoneMedia -d <UDID> --rw --reveal

# 设备还没插好？等待它接入
imount mount ~/iPhoneMedia --wait --timeout 120
```

`mount` 在前台运行以保持挂载。以下任一情况都会自动卸载并清理：
按 `Ctrl-C`、在 Finder 中推出该卷、拔掉数据线。

需要后台常驻：

```bash
nohup imount mount ~/iPhonePhotos > ~/imount.log 2>&1 &
imount umount ~/iPhonePhotos     # 卸载
```

| 选项 | 说明 |
| --- | --- |
| `-d, --device <UDID>` | 指定设备（默认第一台 USB 设备） |
| `-p, --afc-path <路径>` | 设备内路径；默认 `/`（整个媒体库），`/DCIM` 为相机胶卷 |
| `--readonly / --rw` | 只读（默认）/ 读写 |
| `-n, --volume-name <名称>` | Finder 中显示的卷名 |
| `--reveal` | 挂载后用 Finder 打开 |
| `-w, --wait` / `--timeout` | 等待设备接入 / 超时秒数 |
| `--host` / `--port` | 本机 WebDAV 监听地址 / 端口（默认随机） |

### 2. 设备与环境

```bash
imount doctor          # 检查 usbmuxd、mount_webdav、依赖、设备数
imount devices         # 列出已连接设备（--json 便于脚本处理）
imount info            # 设备详细信息
imount -v              # 查看版本（同 --version）
```

### 3. 只提供 WebDAV 地址（不自动挂载）

```bash
imount serve -p /     # 暴露整个媒体库（默认即 /）
# 输出形如 http://127.0.0.1:xxxxx/
# 可在 Finder「前往 → 连接服务器」输入，或手动：
#   mount_webdav -S http://127.0.0.1:xxxxx/ ~/mnt
```

### 4. 增量同步（不挂载）

适合只想定期备份照片、或环境不方便挂载时：

```bash
imount sync ~/iPhonePhotos -p /DCIM              # 增量镜像（按 大小+修改时间 跳过未变化文件）
imount sync ~/iPhonePhotos -p /DCIM --dry-run    # 只预览，不写盘
imount sync ~/iPhonePhotos -p /DCIM --delete     # 让本地与设备严格一致（删除本地多余文件）
```

### 5. 浏览设备文件 / 无真机自检

```bash
imount ls / -r -l                                # 递归列出设备媒体库（带大小）
imount ls /DCIM -l                               # 只看相机胶卷
imount demo ~/Pictures ~/mnt_demo -p /           # 用本地目录模拟设备，验证挂载链路
```

---

## 🔧 工作原理

```text
┌──────────────┐   USB / Lockdown   ┌──────────────────────────────┐
│ iPhone/iPad  │ ◀────────────────▶ │ pymobiledevice3 (AFC)        │
│  /var/mobile │                    │  com.apple.afc               │
│    /Media    │                    └───────────────┬──────────────┘
│      /DCIM   │                                    │ 读写
└──────────────┘                                    ▼
                                    ┌──────────────────────────────┐
                                    │ 本机 WebDAV 服务 (asgiwebdav) │
                                    │ http://127.0.0.1:<随机端口>/  │
                                    └───────────────┬──────────────┘
                                                    │ mount_webdav
                                                    ▼
                                    ┌──────────────────────────────┐
                                    │  ~/iPhonePhotos  (真实挂载卷) │
                                    │  Finder / Preview / cp 可用   │
                                    └──────────────────────────────┘
```

1. AFC（Apple File Conduit）服务 `com.apple.afc` 暴露设备上的 `/var/mobile/Media`，
   照片视频位于其下的 `/DCIM`。macOS 自带 `usbmuxd`，`pymobiledevice3` 直接使用它，
   **无需再装 libimobiledevice / usbmuxd**。
2. 用一个用户态 WebDAV 服务把 AFC 文件系统桥接出来。
3. macOS 原生 `mount_webdav` 把它挂载成一个真实卷 —— 完全绕开内核扩展。

### 为什么不用 macFUSE？

| 方案 | 说明 | 结论 |
| --- | --- | --- |
| **AFC + WebDAV + `mount_webdav`** | pymobiledevice3 提供 AFC 与 WebDAV 桥接；macOS 原生挂载 WebDAV | ✅ **本项目采用**：无 kext、无额外守护进程、真实挂载卷 |
| macFUSE + `fusepy`/`pyfuse3` | 经典 FUSE，需安装 macFUSE 内核扩展（Apple Silicon 上还需安全设置与重启） | ❌ 依赖重、易受系统版本影响 |
| libimobiledevice + `ifuse` | 跨平台 FUSE，需自编译，其 `usbmuxd` 与 macOS 原生冲突 | ❌ 维护成本高 |
| `go-ios` | Go 实现，含 FUSE 挂载 | 🔶 需引入 Go 工具链 |
| Apple **FSKit**（macOS 15.4+） | 官方用户态文件系统框架 | 🔷 未来可关注 |

### 一个实现上的坑（已修复）

WebDAV 服务与挂载卷由**同一个 Python 进程**提供。因此**绝不能在服务进程内
`stat` / `ls` 挂载点**：该文件系统调用会阻塞事件循环，而事件循环正是要响应
`webdavfs` 发来的 HTTP 请求，于是死锁。imount 内部一律通过内核挂载表
（`mount` 命令）判断挂载状态，其它进程（Finder、Shell、`cp`）访问挂载点则完全正常。

---

## 🩺 故障排查

**设备检测不到（`imount devices` 为空）**

1. 使用**能传数据**的线（很多线只能充电），直连 Mac，避免无源 Hub；
2. 解锁设备，弹窗点「信任此电脑」并输入密码；
3. 曾点过「不信任」：设备上 *设置 → 通用 → 传输或还原 → 还原 → 还原位置与隐私*，再重插；
4. Wi-Fi 方式：先用线连一次并在 Finder 勾选「通过 Wi-Fi 同步」，且同一局域网；
5. 运行 `imount doctor`，或 `ioreg -p IOUSB` 确认是否出现新 USB 节点。

**看不到全部照片**
`/DCIM` 就是相机胶卷的原始文件。若开启了「iCloud 照片 → 优化 iPhone 存储空间」，
部分原图可能尚未下载到本机，设备上就没有对应文件。

**卸载时报「资源忙」**
先关闭正在读取该卷的 App（预览、播放器），再执行 `imount umount <目录>`（默认带 `--force`）。

**为什么默认只读？**
只读能避免误删/误改设备照片库。确需写入用 `--rw`。

**需要开发者模式吗？**
不需要。AFC（`com.apple.afc`）是普通服务，信任设备即可。

---

## 🧑‍💻 开发

```bash
make dev        # 创建 .venv 并安装开发依赖
make test       # 运行测试（无需真机）
make demo       # 用本地目录模拟设备，验证挂载链路
make doctor     # 环境自检
```

测试通过「本地目录模拟 AFC + 真实 WebDAV 服务 + 真实 `mount_webdav`」，在**没有
iOS 设备**的情况下验证完整挂载/读/写/卸载生命周期。测试中读取挂载点一律通过子进程
完成，以规避上文提到的进程内死锁。

### 项目结构

```text
imount/
├── install.sh                 # 一键安装 / 卸载
├── imount/
│   ├── cli.py                 # Typer 命令行（子命令入口）
│   ├── device.py              # 设备发现 / lockdown 连接管理
│   ├── errors.py              # 异常类型
│   ├── util.py                # 命令执行、内核挂载表判断等
│   ├── local_afc.py           # 本地目录模拟 AFC（demo / 测试用）
│   └── backends/
│       ├── webdav.py          # WebDAV 服务 + mount_webdav 生命周期（核心）
│       └── mirror.py          # 增量同步后端
├── tests/                     # 无需真机的端到端挂载测试
├── pyproject.toml
├── Makefile
└── README.md
```

### 命令一览

| 命令 | 作用 |
| --- | --- |
| `imount mount <目录>` | 挂载设备目录到指定目录（默认整个媒体库） |
| `imount umount <目录>` | 卸载 |
| `imount devices` | 列出已连接设备 |
| `imount info` | 设备详情 |
| `imount doctor` | 环境自检 |
| `imount serve` | 只启动 WebDAV 服务 |
| `imount ls [路径]` | 列出设备文件 |
| `imount sync <目录>` | 增量同步到本地（默认 /DCIM） |
| `imount demo <源> <目录>` | 用本地目录模拟设备做自检 |
| `imount -v` / `--version` | 显示版本 |

---

## 许可证

MIT
