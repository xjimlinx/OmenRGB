#!/usr/bin/env bash
# Install the omen-rgb-keyboard kernel driver (DKMS), udev rules and
# input-group permissions on Ubuntu/Debian, Fedora, Arch or openSUSE.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_DIR=""

if [ "$EUID" -ne 0 ]; then
  echo ">> 需要 root 权限，正在用 sudo 重新执行 ..."
  exec sudo -E bash "$0" "$@"
fi

for CAND in "$SCRIPT_DIR/omen-rgb-keyboard-main" "$SCRIPT_DIR/omen-rgb-keyboard"; do
  if [ -f "$CAND/src/core/omen_rgb_keyboard_main.c" ]; then
    DRIVER_DIR="$CAND"
    break
  fi
done

if [ -z "$DRIVER_DIR" ]; then
  echo ">> 未找到驱动源码，正在从 GitHub 克隆 omen-rgb-keyboard ..."
  git clone --depth 1 https://github.com/OmenLinux/omen-rgb-keyboard.git "$SCRIPT_DIR/omen-rgb-keyboard"
  DRIVER_DIR="$SCRIPT_DIR/omen-rgb-keyboard"
fi

echo "=== [1/7] 安装编译依赖 ==="
if command -v pacman >/dev/null 2>&1; then
  pacman -S --needed --noconfirm dkms base-devel linux-headers alsa-lib
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    "linux-headers-$(uname -r)" build-essential dkms libasound2-dev
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y dkms kernel-devel kernel-headers "@development-tools" alsa-lib-devel
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install dkms kernel-devel kernel-source gcc make alsa-devel
else
  echo "!! 无法识别的发行版，请手动安装: linux-headers, dkms, gcc, make, alsa 开发包" >&2
  exit 1
fi

echo "=== [2/7] 解除与 hp_wmi 的冲突 ==="
if lsmod | grep -q '^hp_wmi'; then
  modprobe -r hp_wmi 2>/dev/null || true
fi
if [ ! -f /etc/modprobe.d/blacklist-hp.conf ]; then
  echo "blacklist hp_wmi" > /etc/modprobe.d/blacklist-hp.conf
fi

echo "=== [3/7] 编译并安装驱动 (DKMS) ==="
cd "$DRIVER_DIR"
make install

echo "=== [4/7] 配置自动加载与状态目录 ==="
cp omen_rgb_keyboard.conf /etc/modprobe.d/
echo "omen_rgb_keyboard" > /etc/modules-load.d/omen_rgb_keyboard.conf
mkdir -p /var/lib/omen-rgb-keyboard
chmod 755 /var/lib/omen-rgb-keyboard

echo "=== [5/7] 加载驱动 ==="
modprobe omen_rgb_keyboard || true
if ! lsmod | grep -q '^omen_rgb_keyboard'; then
  echo
  echo "!! 驱动未能加载，请查看原因:" >&2
  echo "   dmesg | grep -i omen" >&2
  if mokutil --sb-state 2>/dev/null | grep -qi enabled; then
    echo "   Secure Boot 已启用：未签名的模块会被拒绝（Key was rejected by service）。" >&2
    echo "   处理方式: a) 关闭 Secure Boot;  b) 生成 MOK 密钥并为 DKMS 配置自动签名。" >&2
  fi
  exit 1
fi

echo "=== [6/7] 安装 udev 规则并加入 input 组 ==="
cd "$DRIVER_DIR"
bash install-udev-rules.sh

echo "=== [7/7] 验证 ==="
if [ -d /sys/devices/platform/omen-rgb-keyboard/rgb_zones ]; then
  echo ">> sysfs 接口已就绪:"
  ls /sys/devices/platform/omen-rgb-keyboard/rgb_zones/
  echo ">> 当前亮度: $(cat /sys/devices/platform/omen-rgb-keyboard/rgb_zones/brightness)%"
else
  echo "!! sysfs 接口未出现，请运行 'sudo dmesg | grep -i omen' 查看原因" >&2
  exit 1
fi

echo
echo "驱动安装完成。"
echo "如果你被加入了 input 组，请注销后重新登录（或运行 newgrp input）再使用 GUI。"
echo "下一步: sudo ./install-gui.sh"
