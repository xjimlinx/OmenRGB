#!/usr/bin/env bash
# Install the OMEN RGB GUI tool and CLI.
#
# Default: system-wide install (/usr/local) - requires root.
#   sudo ./install-gui.sh
# User install (no root needed):
#   ./install-gui.sh --user
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="system"

for arg in "$@"; do
  case "$arg" in
    --user) MODE="user" ;;
    --help|-h)
      echo "用法: $0 [--user]"
      exit 0
      ;;
  esac
done

if [ "$MODE" = "system" ] && [ "$EUID" -ne 0 ]; then
  exec sudo -E bash "$0" "$@"
fi

if [ "$MODE" = "system" ]; then
  PREFIX="/usr/local"
  LIB_DIR="$PREFIX/lib/omenrgb"
  BIN_DIR="$PREFIX/bin"
  APP_DIR="/usr/share/applications"
  ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
else
  PREFIX="$HOME/.local"
  LIB_DIR="$PREFIX/lib/omenrgb"
  BIN_DIR="$PREFIX/bin"
  APP_DIR="$PREFIX/share/applications"
  ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
fi

echo "=== 安装到 $LIB_DIR ==="
mkdir -p "$LIB_DIR" "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
rm -rf "$LIB_DIR"
cp -r "$SCRIPT_DIR/omenrgb" "$LIB_DIR"

echo "=== 安装启动脚本 ==="
cp "$SCRIPT_DIR/bin/omenrgb" "$BIN_DIR/omenrgb"
cp "$SCRIPT_DIR/bin/omenrgb-gui" "$BIN_DIR/omenrgb-gui"
chmod 755 "$BIN_DIR/omenrgb" "$BIN_DIR/omenrgb-gui"

echo "=== 安装桌面入口 ==="
if [ "$MODE" = "system" ]; then
  EXEC="/usr/local/bin/omenrgb-gui"
else
  EXEC="$HOME/.local/bin/omenrgb-gui"
fi
cat > "$APP_DIR/omenrgb.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OMEN RGB 键盘控制器
Name[en]=OMEN RGB Keyboard Control
Comment=控制 HP OMEN 4 分区 RGB 键盘背光
Comment[en]=Control HP OMEN 4-zone RGB keyboard lighting
Exec=$EXEC
Icon=omenrgb
Terminal=false
Categories=Settings;HardwareSettings;Utility;
EOF

echo "=== 安装图标 ==="
cp "$SCRIPT_DIR/icons/omenrgb.svg" "$ICON_DIR/omenrgb.svg"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$(dirname "$ICON_DIR")" >/dev/null 2>&1 || true
fi

echo
echo "安装完成！"
echo "  启动 GUI: $EXEC"
echo "  命令行:   $BIN_DIR/omenrgb --help"
echo
echo "若桌面环境没有立刻显示图标，注销重新登录即可。"
