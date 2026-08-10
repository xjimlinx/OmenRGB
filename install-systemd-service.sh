#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# 把 omenrgb 安装成系统应用（Rust 原生二进制，无 Python 依赖）：
#   1) 构建 release 二进制（CLI / 守护进程 / GUI）
#   2) root systemd 守护进程（omenrgbd）+ Unix socket，普通用户免密改色
#   3) 应用菜单入口（omenrgb.desktop）+ 图标
#   4) /usr/local/bin 下的 omenrgb / omenrgb-gui / omenrgbd
#
# 用法:
#   sudo ./install-systemd-service.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"
GROUP_NAME="$(id -gn "$USER_NAME")"
UNIT="/etc/systemd/system/omenrgb.service"

# ---------- 0. 构建 Rust release ----------
if ! command -v cargo >/dev/null 2>&1; then
    echo "错误: 未找到 cargo，请先安装 Rust 工具链。" >&2
    exit 1
fi
(cd "$REPO/rust" && cargo build --release)

# ---------- 1. systemd 守护进程 ----------
cat > "$UNIT" <<EOF
[Unit]
Description=OMEN RGB keyboard lighting daemon
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/bin/omenrgbd
RuntimeDirectory=omenrgb
RuntimeDirectoryMode=0755
Environment=OMENRGB_SOCK_USER=$USER_NAME
Environment=OMENRGB_SOCK_GROUP=$GROUP_NAME
Restart=on-failure
RestartSec=2
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# 干净交接：先停掉旧实现（如 Python daemon），再启动新的 Rust 二进制
systemctl stop omenrgb 2>/dev/null || true
rm -f /run/omenrgb/control.sock
systemctl enable --now omenrgb

# ---------- 2. 二进制 ----------
rm -f /usr/local/bin/omenrgb /usr/local/bin/omenrgb-gui /usr/local/bin/omenrgbd
install -m 0755 "$REPO/rust/target/release/omenrgb" /usr/local/bin/omenrgb
install -m 0755 "$REPO/rust/target/release/omenrgbd" /usr/local/bin/omenrgbd
install -m 0755 "$REPO/rust/target/release/omenrgb-gui" /usr/local/bin/omenrgb-gui

# ---------- 3. 图标（参考 OGH 重绘，多尺寸） ----------
for SZ in 32 48 64 128 256 512; do
    DEST="/usr/share/icons/hicolor/${SZ}x${SZ}/apps"
    mkdir -p "$DEST"
    install -m 0644 "$REPO/icons/omenrgb-${SZ}.png" "$DEST/omenrgb.png"
done
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# ---------- 4. 应用菜单 ----------
install -m 0644 "$REPO/omenrgb.desktop" /usr/share/applications/omenrgb.desktop
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

echo
echo "已安装为系统应用："
echo "  · 服务:   omenrgb.service（已启用并启动）"
echo "  · 命令:   /usr/local/bin/omenrgb / omenrgb-gui"
echo "  · 菜单:   OMEN RGB 键盘控制器（带图标）"
echo "普通用户 $USER_NAME 可免密使用。验证:"
echo "  systemctl status omenrgb"
echo "  omenrgb status"
echo "卸载:"
echo "  sudo systemctl disable --now omenrgb && sudo rm $UNIT /usr/share/applications/omenrgb.desktop"
echo "  sudo rm /usr/local/bin/omenrgb /usr/local/bin/omenrgb-gui /usr/local/bin/omenrgbd"
echo "  sudo rm -r /usr/share/icons/hicolor/{32,48,64,128,256,512}x*/apps/omenrgb.png"
echo "  sudo systemctl daemon-reload"
