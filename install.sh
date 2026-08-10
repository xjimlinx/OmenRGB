#!/usr/bin/env bash
# One-shot install: kernel driver + GUI tool.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "########## 1/2 安装内核驱动 ##########"
sudo bash "$SCRIPT_DIR/install-driver.sh"

echo
echo "########## 2/2 安装 GUI 工具 ##########"
sudo bash "$SCRIPT_DIR/install-gui.sh"

echo
echo "全部完成！注销并重新登录（使 input 组成员生效）后运行: omenrgb-gui"
