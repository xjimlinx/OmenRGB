# OMEN 16 RGB 键盘 Linux 控制 — 交接文档

> 给 Linux 侧 agent 的完整上下文。本机（Windows）已完成协议确认与代码实现，
> 你在 Linux 上的首要任务：**按第 5 节跑通 WMI 探测与写色**，把输出贴回来验证。

---

## 1. 一句话结论

这台 **HyperX OMEN Gaming Laptop 16-ap1xxx** 的 4 分区 RGB 键盘（USB VID/PID
`0C45:7D1C`）**固件原生支持标准 HP WMI 背光接口**，不需要逆向 HID 协议，也不需要
任何内核补丁——只要 Linux 上有 `acpi_call` 模块，就能通过 `\_SB.WMID.WMAA` 直接
读写 4 个分区的颜色和亮度。

之前"WMI 怎么操作都失效"的原因：调用了**固件中不存在的旧 OMEN GUID**
（`5FB7F034-2C63-45E9-948E-67B7AAC416DB`）。正确 GUID 是
`5FB7F034-2C63-45E9-BE91-3D44E2C707E4`。

---

## 2. 硬件与固件事实（已核实，勿再推翻）

### 2.1 键盘 USB 结构

- 名称：HP Gaming Keyboard（Microdia），VID `0x0C45` / PID `0x7D1C`
- 复合 HID 设备：
  - MI_00 / MI_02：标准键盘（按键输入）
  - MI_01 Col01：消费控制（0x0C）
  - MI_01 Col02：厂商定义（0xFFFF），4 字节输入
  - **MI_03：厂商定义（UsagePage `0xFF90`/Usage `0xFF00`），In=65 / Out=65 /
    Feat=65 字节 ← RGB 通道**
- 结论：**RGB 与按键输入物理分离**，但 RGB 控制**同时**有 WMI 路径（见下），
  HID 协议逆向只在 WMI 路径彻底失败时才需要。

### 2.2 DSDT 证据（已反汇编核实）

反汇编文件：`research/aml/DSDT.dsl`（本仓库内）。

- `\_SB.WMID` 设备的 `_WDG` 第一条就是标准 HP WMI GUID
  `5FB7F034-2C63-45E9-BE91-3D44E2C707E4`，控制方法 **WMAA**。
- **旧 OMEN GUID `5FB7F034-…-948E-67B7AAC416DB` 在整个 DSDT/SSDT 中不存在**。
- `WMAA(3 参数)` → `HWMC(Arg1, Arg2)`，命令分派：
  - `COMD == 0x00020008`（Gaming）：`CMDT == 0x2B` 读键盘类型（EC `RE20`）
  - `COMD == 0x00020009`（背光）：`CMDT 0x01` 能力、`0x02` 读颜色表、
    `0x03` 写颜色表、`0x04` 读亮度、`0x05` 写亮度
- 颜色表：128 字节，**RGB 从偏移 `0x19`（25）开始，每分区 3 字节（R G B）**，
  共 4 分区 12 字节，写入 EC 字段 `LRGB`/`BRGB`（各 96 位）后置 `LCMC=1` 生效。
- 亮度：EC 字段 `LBRT`，`0xE4`=开、`0x64`=关。

### 2.3 与上游的关系

- 2026-06-14 提交的**主线 hp-wmi 补丁 v10**（multicolor LED，4 分区）用的正是这套
  ABI：`research/hp-wmi-multicolor-v10.patch`。补丁**尚未合入 mainline**
  （2026-08-09 检查 `torvalds/linux` master 无 `HPWMI_BACKLIGHT`）。
  - 若未来内核合入，会出现 `/sys/class/leds/hp::kbd_zoned_backlight-{right,center,left,wasd}`，
    本工具已有 `MainlineBackend` 自动适配。
- 旧 OmenLinux/omen-rgb-keyboard 驱动（`omen-rgb-keyboard-main/`）针对不同 GUID，
  **在这台机器上不适用**，不要再装它。

---

## 3. WMI ABI 完整规范（Linux agent 请以此为准）

### 3.1 调用格式

```
\_SB.WMID.WMAA <instance=0> <mid> b<输入缓冲 hex>
```

输入缓冲（小端）：

| 偏移 | 长度 | 内容 |
|------|------|------|
| 0x00 | 4 | 签名 `0x55434553`（"SECU"） |
| 0x04 | 4 | 命令：`0x00020009` 背光 / `0x00020008` Gaming |
| 0x08 | 4 | 命令类型 CMDT（见下表） |
| 0x0C | 4 | 数据长度（载荷字节数） |
| 0x10 | N | 载荷 |

`mid` = 输出长度编码：outsize 0→1、1~4→2、5~128→3、129~1024→4。

### 3.2 命令类型

| COMD | CMDT | 功能 | outsize / mid |
|------|------|------|----------------|
| 0x20008 | 0x2B | 读键盘类型（EC RE20） | 4 / 2 |
| 0x20009 | 0x01 | 读能力 | 4 / 2 |
| 0x20009 | 0x02 | 读颜色表（128B） | 128 / 3 |
| 0x20009 | 0x03 | 写颜色表（128B，RGB 在偏移 0x19） | 128 / 3 |
| 0x20009 | 0x04 | 读亮度（LBRT） | 4 / 2 |
| 0x20009 | 0x05 | 写亮度（载荷 1 字节） | 1 / 2 |

键盘类型（RE20）：0=无背光、1=四分区带数字键盘、2=四分区无数字键盘、
3=RGB 每键、4=单分区带数字键盘、5=单分区无数字键盘。本机应为 **1**。

### 3.3 响应格式

```
[0x00] u32 签名 0x53534150（"PASS"）成功
[0x04] u32 RETC（0 = 成功）
[0x08] 数据 ...
```

颜色读回：数据区偏移 `0x19 + 分区*3`，依次 R、G、B。
分区顺序（内核补丁命名）：0=right、1=center、2=left、3=wasd。

### 3.4 acpi_call 模块限制（重要）

- 输出缓冲固定 **256 字节**（`BUFFER_SIZE`）：136 字节的读颜色响应只显示前 42
  字节，**第 4 分区颜色会被截掉**。→ 需把源码中 `#define BUFFER_SIZE 256`
  改成 `2048` 后重编译（见第 5 节）。
- 输入上限 512 字符：128 字节载荷 + 16 字节头 = 288 hex 字符，没问题。
- `/proc/acpi/call` 只有 root 可写；内核 Secure Boot 可能拒绝未签名模块。

---

## 4. 已交付代码（位于本仓库）

> Windows 路径 `E:\Code\OmenRGB`，Linux 侧预计 `/Code/OmenRGB`（若不同，用
> `find / -maxdepth 4 -name OmenRGB 2>/dev/null` 定位）。

| 文件 | 作用 |
|------|------|
| `omenrgb/wmi_backend.py` | **acpi_call 直调 WMI 后端**（新增，主推） |
| `omenrgb/core.py` | 后端探测（优先级：驱动 sysfs → 主线 LED → WMI）、诊断已接入 WMI |
| `omenrgb/cli.py` / `gui.py` | 命令行 / tkinter 图形界面（自动选用后端） |
| `tools/wmi_probe_linux.py` | **独立探测脚本**（只读探测 + `--set`/`--zone`/`--bright` 写色） |
| `tests/test_wmi_backend.py` | WMI 后端单元测试（含模拟固件，5 项全过，Windows 上可跑） |
| `tools/capture_rgb_windows.ps1` | Windows USBPcap 抓包（加固版，备用路线） |
| `tools/analyze_omen_capture.py` | 分析 0C45:7D1C 抓包（备用） |
| `research/hp-wmi-multicolor-v10.patch` | 主线补丁原文（ABI 对照） |
| `research/aml/DSDT.dsl` | 本机 DSDT 反汇编（证据） |
| `research/hyperx_alloy_origins.md` 等 | HID 协议对照资料（备用） |
| `README.md` | 已更新：WMI 快速开始 + 修正旧结论 |

后端自动选择顺序：`OmenRGB`（旧驱动，本机无）→ `MainlineBackend`（主线 LED，
未合入则无）→ `WmiAcpiBackend`（acpi_call，本机可用）。

---

## 5. Linux 操作步骤（首要任务）

### 5.1 安装 acpi_call 并扩大输出缓冲

```bash
# Debian/Ubuntu
sudo apt install acpi-call-dkms dkms

# 扩大输出缓冲（否则读回颜色会被截断）
sudo sed -i 's/#define BUFFER_SIZE 256/#define BUFFER_SIZE 2048/' \
    /usr/src/acpi_call-*/acpi_call.c
ver=$(ls /usr/src | sed -n 's/^acpi_call-//p' | head -1)
sudo dkms remove acpi_call/$ver --all
sudo dkms add /usr/src/acpi_call-$ver
sudo dkms build acpi_call/$ver -k "$(uname -r)"
sudo dkms install acpi_call/$ver -k "$(uname -r)"
sudo modprobe acpi_call
```

Arch：AUR 包 `acpi_call-dkms`，同样改 `BUFFER_SIZE` 后重建。

验证：
```bash
ls /proc/acpi/call && echo OK
```

### 5.2 只读探测

```bash
cd /Code/OmenRGB   # 或实际路径
sudo python3 tools/wmi_probe_linux.py
```

**预期输出**（供对照）：

```
== 读取键盘类型 (0x20008 / 0x2B) ==
  RE20=1 -> 四分区 带数字键盘

== 读取背光能力 (0x20009 / 0x01) ==
  返回: 07 00 00 00

== 读取亮度 (0x20009 / 0x04) ==
  LBRT=0xE4 (228)

== 读取颜色表 (0x20009 / 0x02) ==
  收到 136 字节
  分区 1: #xxxxxx  ...
```

若显示"颜色数据被截断"，说明 BUFFER_SIZE 补丁没生效，重做 5.1。

### 5.3 写色验证

```bash
sudo python3 tools/wmi_probe_linux.py --set FF0000      # 4 分区全红
sudo python3 tools/wmi_probe_linux.py --zone 0 00FF00   # 分区 1 变绿
sudo python3 tools/wmi_probe_linux.py --bright 75
```

眼睛确认键盘颜色变化。**同时逐区写色，记录"GUI 分区 1-4"与键盘实际区域的对应
关系**（固件顺序 right/center/left/wasd，物理对应待确认）。

### 5.4 使用 GUI / CLI

```bash
./bin/omenrgb status        # 应显示 后端: hp-wmi-acpi
./bin/omenrgb set-all 00FF00
./bin/omenrgb-gui
```

（若尚未安装：`sudo ./install-gui.sh` 或 `./install-gui.sh --user`；本工具纯
Python 标准库，GUI 依赖 tkinter。）

---

## 6. 需要 Linux agent 完成/验证的事项

1. **跑通 5.2 探测**，把完整输出贴回（或截图）。重点核对：键盘类型=1、
   PASS/RETC=0、4 个分区颜色可读。
2. **跑通 5.3 写色**，确认键盘变色；逐区写色并记录分区映射。
3. 若有报错，按第 7 节排查后反馈。
4. （可选）验证主线 LED 路径：`ls /sys/class/leds | grep kbd`，若出现
   `hp::kbd_zoned_backlight-*` 则直接测 `omenrgb status`（会用 MainlineBackend）。
5. （可选，需内核源码）把 `research/hp-wmi-multicolor-v10.patch` 应用到内核，
   可获得无 acpi_call 依赖的 /sys/class/leds 方案。

---

## 7. 故障排查

### RETC 错误码

1=成功、2=签名错误、3=未知命令、4=未知 CMDT、5=数据长度错误、6=数据值错误。

### 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `/proc/acpi/call` 不存在 | acpi_call 未装/未加载 | `apt install acpi-call-dkms`；`modprobe acpi_call` |
| `Error: AE_NOT_FOUND` | 方法路径/实例错 | 用脚本默认路径 `\_SB.WMID.WMAA 0 <mid> b…`，勿改动 |
| 颜色表被截断 | BUFFER_SIZE=256 未改 | 重做 5.1；改完确认 `grep BUFFER_SIZE /usr/src/acpi_call-*/acpi_call.c` |
| 写 /proc/acpi/call 权限拒绝 | 非 root | `sudo` 运行 |
| 模块加载失败（Secure Boot） | 未签名 DKMS 模块被拒 | 关 Secure Boot 或 MOK 签名 |
| 返回签名 FAIL | 命令不受支持（RETC 非 0） | 按 RETC 对照；若 RETC=3/4 说明固件版本不同，贴输出 |
| 写色成功但灯不变 | 亮度为 0/关 | 先 `--bright 75`；确认 `LBRT=0xE4` |

### 诊断命令

```bash
lsmod | grep acpi_call
dmesg | grep -i acpi_call
sudo ./bin/omenrgb diagnose    # 或 sudo python3 omenrgb/cli.py diagnose
```

---

## 8. 备用路线（仅当 WMI 路径确认不可用）

### 8.1 Windows 抓包（已定位失败原因）

上次抓包空目录的原因是：**USBPcap 驱动已安装但未挂到任何 USB 根集线器**
（`tshark -D` 无 USBPcap 接口）。修复：重装 USBPcap 1.5.4（desowin.org/usbpcap）
并重启，然后用 `tools/capture_rgb_windows.ps1`（已加固：带日志、进程校验、接口
检查）按提示逐区改色抓包，再把整个输出文件夹交给 agent 用
`tools/analyze_omen_capture.py` 分析。

### 8.2 HID 协议参考

- `research/hyperx_alloy_origins.md` / `hyperx_alloy_elite.md`：OpenRGB 文档
- `research/hyperx-keyboard-rgb/`、`research/rgb_keyboard/`：Python/C++ 参考实现
- `D:\Misc\Omen-RGB-Ki\probe_hid5.py`（Linux 侧 `/Code/Misc/Omen-RGB-Ki/`）：
  已尝试 USBDEVFS 断开 usbhid + EP0x05 bulk 写，模式 `0x81 R G B`（未确认有效，
  仅当 WMI 失败时继续此方向）。

---

## 9. 关键技术文件路径速查

```text
/Code/OmenRGB/
├── omenrgb/wmi_backend.py          # WMI 后端（读我）
├── tools/wmi_probe_linux.py        # 探测脚本（先跑这个）
├── tests/test_wmi_backend.py       # 单元测试
├── research/aml/DSDT.dsl           # DSDT 反汇编（证据）
├── research/hp-wmi-multicolor-v10.patch
├── README.md
└── bin/omenrgb{, -gui}
```
