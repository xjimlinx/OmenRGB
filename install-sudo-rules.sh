#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# 一次性安装 OMEN RGB 工具的 sudo 免密规则（仅两个固定脚本，最小权限）。
#
# 之后 omenrgb CLI 和 GUI 都可以由普通用户直接运行（内部通过这两个
# 限定路径的脚本以 root 访问 /proc/acpi/call 与 /dev/mem 的 KBAM 寄存器），
# 无需再输密码。规则只放行固定命令，不授予任意 root。
#
# 用法:
#   sudo ./install-sudo-rules.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/etc/sudoers.d/zz-omenrgb"

# 被授予免密权限的普通用户：以 sudo 运行本脚本时取 SUDO_USER（调用者），
# 否则回退到 wheel 组。
WHO="${SUDO_USER:-}"
if [ -z "$WHO" ]; then
    WHO="%wheel"
fi

cat > "$DEST" <<EOF
# OMEN RGB 键盘工具免密规则（只放行本仓库的固定脚本，不带任意 root）
$WHO ALL=(root) NOPASSWD: /usr/bin/python3 $REPO/tools/wmi_call.py
$WHO ALL=(root) NOPASSWD: /usr/bin/python3 $REPO/tools/wmi_call.py *
$WHO ALL=(root) NOPASSWD: /usr/bin/python3 $REPO/tools/hid_probe_linux.py
$WHO ALL=(root) NOPASSWD: /usr/bin/python3 $REPO/tools/hid_probe_linux.py *
EOF

chmod 440 "$DEST"
visudo -c -f "$DEST"

echo
echo "已安装: $DEST"
echo "现在可以用普通用户直接运行:"
echo "  omenrgb status"
echo "  omenrgb set-all 00FF00"
echo "  omenrgb-gui"
echo
echo "验证: sudo -n /usr/bin/python3 $REPO/tools/wmi_call.py 20009 02"
