# OMEN RGB 键盘控制工具

为 **HP OMEN / HyperX OMEN 笔记本的 4 分区 RGB 键盘** 编写的 Linux 图形控制工具（附带命令行接口），针对你手上的这台 **HyperX OMEN Gaming Laptop 16-ap1xxx** 做了适配。

## 工作原理

```
┌────────────┐   sysfs 读写   ┌───────────────────────────────┐
│  GUI/CLI   │ ─────────────▶ │ omen-rgb-keyboard 内核驱动     │
│ (tkinter)  │                │ /sys/devices/platform/        │
└────────────┘                │   omen-rgb-keyboard/rgb_zones/ │
                              └───────────────┬───────────────┘
                                              │ HP WMI 命令 (GUID
                                              │ 5FB7F034-…)
                                              ▼
                                      笔记本固件/键盘 EC

                            ┌──────────────────────────────────────┐
  GUI/CLI (另一条路) ─────▶ │ acpi_call (/proc/acpi/call) 直调 WMI │
                            │ \\_SB.WMID.WMAA（无需内核驱动/补丁） │
                            └──────────────────┬───────────────────┘
                                               ▼
                                       笔记本固件/键盘 EC
```

底层有三条可用路径，工具自动按优先级选择：

1. **omen-rgb-keyboard 内核驱动**（DKMS，支持 4 分区颜色、亮度、11 种动画、状态持久化）——但注意：该上游驱动针对旧版 OMEN WMI GUID，**在这台 16-ap1xxx 上不适用**（见下方说明）。
2. **主线 hp-wmi 多色 LED**（`/sys/class/leds/hp::kbd_zoned_backlight-*`）——内核补丁 v10 已提交但尚未合入 mainline，合入后自动生效（仅静态颜色）。
3. **acpi_call 直调 WMI**（`/proc/acpi/call` + `\_SB.WMID.WMAA`）——**本机已验证固件支持**，无需任何内核补丁/驱动，推荐当前使用。

> **重要事实（HyperX OMEN 16-ap1xxx，已通过 DSDT 反汇编确认）**：
> 这台机器的 DSDT 只暴露了标准 HP WMI GUID `5FB7F034-2C63-45E9-BE91-3D44E2C707E4`（WMAA 方法，含 `0x20009` 背光命令：`0x02` 读颜色表、`0x03` 写颜色表、`0x04/0x05` 读写亮度），**没有**旧 OMEN 项目使用的 `5FB7F034-…-948E-67B7AAC416DB` GUID。这就是之前"WMI 怎么操作都失效"的原因——调用的 GUID 在固件里根本不存在。键盘本身仍是 Microdia `0C45:7D1C` 复合 HID 设备，RGB 走厂商接口 MI_03（UsagePage FF90），但那只是底层传输，**固件同时提供完整的 WMI 4 分区颜色表接口**（128 字节表，RGB 从偏移 25 开始，每区 3 字节）。

### 快速开始（无需内核驱动）

```bash
# 1. 安装 acpi_call 模块（Debian/Ubuntu）
sudo apt install acpi-call-dkms dkms

# 2. （推荐）把结果缓冲区从 256 字节扩大到 2048，否则读回 4 个分区颜色会被截断
sudo sed -i 's/#define BUFFER_SIZE 256/#define BUFFER_SIZE 2048/' \
    /usr/src/acpi_call-*/acpi_call.c
ver=$(ls /usr/src | sed -n 's/^acpi_call-//p' | head -1)
sudo dkms remove acpi_call/$ver --all
sudo dkms add /usr/src/acpi_call-$ver
sudo dkms build acpi_call/$ver -k "$(uname -r)"
sudo dkms install acpi_call/$ver -k "$(uname -r)"
sudo modprobe acpi_call

# 3. 先探测（只读）：键盘类型 / 当前颜色 / 亮度
sudo python3 tools/wmi_probe_linux.py

# 4. 试写一个颜色（全部 4 分区变红）
sudo python3 tools/wmi_probe_linux.py --set FF0000
```

探测通过后，`omenrgb` 会自动选用 WMI 后端（`omenrgb status` 显示 `后端: hp-wmi-acpi`），GUI/CLI 用法与下方相同。WMI 后端只支持静态颜色；动画仍需要 omen-rgb-keyboard 驱动。

### 逆向工具

- `tools/hid_probe_windows.py`：Windows 上只读枚举键盘 HID 接口与报告长度（需要真实桌面终端运行，沙箱内部分调用被限制）
- `tools/hid_probe_linux.py`：Linux 上定位 `/dev/hidrawN` 中哪个节点是 RGB 接口（按 VID/PID + 报告描述符识别），并尝试读取当前 feature 报告

## 功能

- **4 分区颜色**：分别设置 zone00-zone03，或一键全区域同色
- **亮度**：0-100%，实时生效
- **11 种动画**：静态、呼吸、彩虹、波浪、脉冲、追逐、闪烁星光、烛光、极光、迪斯科、渐变（渐变支持每个区域自定义颜色序列）
- **预设**：内置 8 个预设，可保存/删除自己的方案（`~/.config/omenrgb/presets.json`）
- **诊断**：一键检查驱动、WMI GUID、权限、Secure Boot、dmesg，直接复制报告
- **权限自适应**：普通用户可直接写入（udev 规则 + input 组）；否则自动尝试 pkexec/sudo 提权

## 安装

### 1. 安装内核驱动 + 工具（一键）

```bash
cd OmenRGB
sudo ./install.sh
```

脚本会：

1. 安装编译依赖（linux-headers、dkms、build-essential、alsa 开发包，按发行版自动选择 pacman/apt/dnf/zypper）
2. 用 DKMS 编译安装 omen-rgb-keyboard 驱动
3. 卸载并 blacklist `hp_wmi`（两者同时加载会互相抢占 WMI 事件）
4. 配置开机自动加载、创建 `/var/lib/omen-rgb-keyboard` 状态目录
5. 安装 udev 规则、把当前用户加入 `input` 组

安装完成后 **注销并重新登录**（让 `input` 组生效），然后启动：

```bash
omenrgb-gui          # 图形界面
omenrgb status       # 命令行查看状态
```

### 分开安装

```bash
sudo ./install-driver.sh    # 只装内核驱动 + 权限
sudo ./install-gui.sh       # 只装 GUI/CLI 到 /usr/local
./install-gui.sh --user     # 或者装到 ~/.local（无需 root）
```

### 不安装、直接运行

仓库内直接运行（需要已装好内核驱动）：

```bash
chmod +x bin/omenrgb bin/omenrgb-gui   # 首次需要给执行权限
./bin/omenrgb-gui
./bin/omenrgb status
```

## 命令行用法

```bash
omenrgb status                  # 查看后端与当前状态
omenrgb diagnose                # 详细诊断报告
omenrgb get zone                # 读取 4 个区域颜色
omenrgb set-all FF0000          # 全部区域红色
omenrgb set-zone 0 00FF00       # 区域 0 绿色
omenrgb brightness 75           # 亮度 75%
omenrgb mode rainbow            # 彩虹动画
omenrgb speed 5                 # 动画速度 5
omenrgb gradient "0,1:FF0000,00FF00;2,3:0000FF,FF00FF"   # 渐变
omenrgb preset list             # 列出预设
omenrgb preset apply 火焰渐变   # 应用预设
omenrgb preset save 我的方案    # 保存当前状态为预设
```

动画模式：`static`、`breathing`、`rainbow`、`wave`、`pulse`、`chase`、`sparkle`、`candle`、`aurora`、`disco`、`gradient`。

## 常见问题排查

先运行 `omenrgb diagnose`，报告会直接指出问题所在。常见原因：

| 现象 | 原因 | 解决 |
|---|---|---|
| 模块加载报 `Key was rejected by service` | Secure Boot 拒绝未签名模块 | 关闭 Secure Boot，或生成 MOK 密钥并为 DKMS 配置自动签名 |
| `dmesg` 显示 WMI GUID not found | 调用了不存在的旧 OMEN GUID | 本机 DSDT 只有 `5FB7F034-…-BE91-3D44E2C707E4`；工具已使用该 GUID，`omenrgb diagnose` 可直接验证 |
| sysfs 存在但写入报权限错误 | 用户不在 `input` 组 | 运行 `sudo ./install-udev-rules.sh` 后注销重登，或 `newgrp input` |
| 颜色不生效 | 亮度为 0；或 `hp_wmi` 与驱动冲突 | 设置亮度 > 0；确认 `/etc/modprobe.d/blacklist-hp.conf` 生效并重启 |
| 驱动装了但没自动加载 | initramfs 未更新 | 重新生成 initramfs（Arch: `mkinitcpio -P`，Ubuntu: `update-initramfs -u`，Fedora: `dracut --force`） |
| 重启后设置丢失 | 状态目录不存在 | `sudo mkdir -p /var/lib/omen-rgb-keyboard && sudo modprobe omen_rgb_keyboard` |
| `hp_wmi` 又回来了 | 内核模块被重新加载 | 确认 blacklist 文件 + 重建 initramfs |

### 和 OmenCtl 的关系

[OmenCtl](https://github.com/yunusemreyl/OmenCtl) 是另一个更完整的 OMEN 控制中心（风扇曲线、功耗、MUX 等，GTK4 + root 守护进程），它的 RGB 部分同样基于 omen-rgb-keyboard 驱动。本工具专注键盘 RGB，依赖更少（纯 Python 标准库）。如果以后需要风扇/功耗控制，可以考虑两者共存或迁移。

## 项目结构

```
OmenRGB/
├── omenrgb/
│   ├── core.py       # 后端：sysfs 读写、后端探测、诊断
│   ├── wmi_backend.py # WMI/acpi_call 后端（无需内核驱动）
│   ├── cli.py        # 命令行接口
│   ├── gui.py        # tkinter 图形界面
│   └── presets.py    # 预设存取 (~/.config/omenrgb/presets.json)
├── bin/              # omenrgb / omenrgb-gui 启动脚本
├── tools/
│   ├── wmi_probe_linux.py      # Linux WMI 探测/写色测试（sudo）
│   ├── capture_rgb_windows.ps1 # Windows USBPcap 抓包（逆向 HID 备用）
│   ├── analyze_omen_capture.py # 分析抓包文件
│   ├── hid_probe_windows.py    # Windows HID 接口枚举
│   └── hid_probe_linux.py      # Linux hidraw 定位
├── tests/
│   └── test_wmi_backend.py     # WMI 后端单元测试（任何平台可跑）
├── install.sh        # 一键安装（驱动 + GUI）
├── install-driver.sh # 只装内核驱动
├── install-gui.sh    # 只装 GUI（支持 --user）
├── icons/            # 应用图标
└── omen-rgb-keyboard-main/   # 上游驱动源码（安装脚本使用）
```

## 测试

在没有 Linux sysfs 的机器上可以通过环境变量模拟：

```bash
export OMENRGB_SYSFS_BASE=/path/to/fake/rgb_zones
python3 tests/test_wmi_backend.py   # WMI 后端单元测试（含模拟固件）
```

## 许可

GPL-3.0。内核驱动部分版权归 OmenLinux 项目。
