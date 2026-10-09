#!/usr/bin/env bash
#
# imount one-click installer for macOS.
#
#   ./install.sh              install (checks dependencies, installs pipx if needed)
#   ./install.sh --uninstall  remove imount
#   ./install.sh -h           help
#
# What it does:
#   1. Verifies macOS and the built-in /sbin/mount_webdav (no macFUSE needed).
#   2. Finds a Python >= 3.10 (installs nothing silently; tells you if missing).
#   3. Ensures `pipx` is available (via Homebrew, else pip --user).
#   4. Installs imount into an isolated pipx environment.
#   5. Makes `imount` available on PATH (via /usr/local/bin, prompting for sudo
#      only if needed).
#   6. Runs `imount doctor` to confirm everything is ready.
#
set -euo pipefail

APP="imount"
PYTHON_MIN="3.10"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$SCRIPT_DIR"

if [[ -t 1 ]]; then
  BOLD="\033[1m"; BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
else
  BOLD=""; BLUE=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

info()  { printf "${BLUE}==>${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET} %s\n" "$*"; }
error() { printf "${RED}✗${RESET} %s\n" "$*" >&2; }
die()   { error "$*"; exit 1; }

usage() {
  awk 'NR==1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
  exit 0
}

find_python() {
  local cand
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 \
       && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$cand"
      return 0
    fi
  done
  return 1
}

pipx_bin_dir() {
  command -v pipx >/dev/null 2>&1 || return 1
  pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin"
}

link_into_path() {
  local src="$1" target="/usr/local/bin/$APP"
  [[ -e "$src" ]] || return 0
  if [[ -w "$(dirname "$target")" ]]; then
    ln -sf "$src" "$target"
  elif command -v sudo >/dev/null 2>&1; then
    info "创建系统链接 $target（可能需要管理员密码）"
    # `sudo -A` uses $SUDO_ASKPASS when present (non-interactive installs);
    # otherwise sudo prompts on the terminal as usual.
    if [[ -n "${SUDO_ASKPASS:-}" ]]; then
      sudo -A ln -sf "$src" "$target" || { warn "创建链接失败，请手动执行：sudo ln -sf '$src' '$target'"; return 0; }
    else
      sudo ln -sf "$src" "$target" || { warn "创建链接失败，请手动执行：sudo ln -sf '$src' '$target'"; return 0; }
    fi
  else
    warn "无法写入 $(dirname "$target")；请把 $(dirname "$src") 加入 PATH"
    return 0
  fi
  ok "已链接 $target -> $src"
}

uninstall() {
  if command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null | grep -q "^$APP "; then
    info "卸载 pipx 环境中的 $APP…"
    pipx uninstall "$APP"
  fi
  if [[ -L "/usr/local/bin/$APP" || -e "/usr/local/bin/$APP" ]]; then
    info "移除 /usr/local/bin/$APP"
    if [[ -w /usr/local/bin ]]; then
      rm -f "/usr/local/bin/$APP"
    elif [[ -n "${SUDO_ASKPASS:-}" ]]; then
      sudo -A rm -f "/usr/local/bin/$APP" || true
    else
      sudo rm -f "/usr/local/bin/$APP" || true
    fi
  fi
  ok "已卸载 $APP。"
  exit 0
}

case "${1:-}" in
  -h|--help) usage ;;
  --uninstall|uninstall) uninstall ;;
esac

printf "${BOLD}imount 安装程序${RESET}\n"

# 1. OS ----------------------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "imount 目前仅支持 macOS（当前系统：$(uname -s)）。"
ok "系统：macOS $(sw_vers -productVersion 2>/dev/null || true)"

# 2. mount_webdav -----------------------------------------------------------
if [[ -x /sbin/mount_webdav ]] || command -v mount_webdav >/dev/null 2>&1; then
  ok "mount_webdav：系统自带（无需 macFUSE / 内核扩展）"
else
  die "未找到 /sbin/mount_webdav，无法挂载 WebDAV 卷。"
fi

# 3. Python -----------------------------------------------------------------
PY="$(find_python || true)"
[[ -n "$PY" ]] || die "未找到 Python >= ${PYTHON_MIN}。请先安装：brew install python"
ok "Python：$("$PY" --version 2>&1)（$PY）"

# 4. pipx -------------------------------------------------------------------
if ! command -v pipx >/dev/null 2>&1; then
  info "未找到 pipx，正在安装…"
  if command -v brew >/dev/null 2>&1; then
    brew install pipx
  else
    "$PY" -m pip install --user pipx
  fi
fi
command -v pipx >/dev/null 2>&1 || die "pipx 安装失败，请手动安装后重试。"
ok "pipx：$(pipx --version)"

# 5. Install ----------------------------------------------------------------
info "安装 $APP（隔离环境，不污染系统 Python）…"
pipx install --force --python "$PY" "$PKG_DIR"

# 6. PATH -------------------------------------------------------------------
BIN_DIR="$(pipx_bin_dir || echo "$HOME/.local/bin")"
link_into_path "$BIN_DIR/$APP"
pipx ensurepath >/dev/null 2>&1 || true

# 7. Verify -----------------------------------------------------------------
echo
if command -v "$APP" >/dev/null 2>&1; then
  ok "安装完成，命令位置：$(command -v "$APP")"
else
  warn "命令暂未进入当前 PATH，新开终端即可使用；或运行：export PATH=\"$BIN_DIR:\$PATH\""
fi
echo
info "运行环境自检："
"$BIN_DIR/$APP" doctor || true
echo
ok "使用 'imount -h' 查看全部命令。"
