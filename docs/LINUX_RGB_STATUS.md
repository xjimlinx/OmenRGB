# OMEN 16 RGB 键盘 Linux 控制 — 最终报告（已成功）

更新于 2026-08-10（**已实机验证：Linux 下可控制键盘 RGB**）

## ✅ 一句话结论

这台 **OMEN 16 (16-ap1xxx, 0C45:7D1C)** 四分区键盘的**实时灯效**由
**EC 邮箱（WMI `0x20009 CMDT 0x0B`）+ LightBarCmdByte 载荷** 驱动，
不是传统颜色表（CMDT 0x03，那只是开机/BIOS 用的）。已实测：

- `device=1, mode=0(static), color_count=4, 4×RGB` → 键盘立即变蓝 ✅
- 同载荷换绿色 → 立即变绿 ✅
- `mode=4`（wave）→ 波浪动画（实测中）

## 真实协议（从 OMEN CC DojoLightingBg.dll 逆向）

命令：`WMAA(0, mid, SECU头 + COMD=0x00020009 + CMDT=0x0B + 128字节载荷)`

载荷（LightBarCmdByte 布局，`HP.Omen.Background.DojoLightingBg`）：

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0 | DEVICE | 0=LightBar 灯条, 1=FourZoneAni 键盘 |
| 1 | MODE | 0=静态; 动画见下表 |
| 2 | CONFIG | 速度/方向/主题组合位 |
| 3 | BRIGHTNESS | 亮度（0-100，实测 100 可用） |
| 4 | TRIBE_INTENSITY | 0 |
| 5 | BASS_INTENSITY | 0 |
| 6 | COLOR_COUNT | 颜色数（静态=4） |
| 7..18 | ZONE1-4 RGB | 每区 3 字节 R,G,B |
| 19..127 | 0 | 填充 |

动画 MODE 字节（`_effectMapping`，effect→mode）：

| 效果 | mode 字节 |
|------|-----------|
| ghosting | 2 |
| ripple | 3 |
| wave | 4 |
| xshape | 6 |
| raindrop | 7 |
| hpanimation | 8 |
| starlight | 9 |
| galaxy | 10 |
| linestreak | 11 |

## 工具用法（已实现）

```bash
sudo omenrgb set-all 00FF00        # 全键变绿（EC 邮箱路径）
sudo omenrgb set-zone 0 FF0000     # 单区
sudo omenrgb brightness 80         # 亮度（随颜色一起下发）
sudo omenrgb animate wave          # 波浪动画（实验性）
sudo omenrgb status                # 状态 + KBAM
sudo omenrgb kbam                  # 键盘模式寄存器
```

## 走过的弯路（已排除）

- **CMDT 0x03 颜色表**：写入/读回都成功，但不驱动实时显示（只影响开机色）。
- **HID 通道（if2/if3）**：0C45:7D1C 的 4 个接口全部无有效灯控应答。
- **KBAM 直写**：只是状态镜像，写它不切换模式。
- 真正入口藏在 OMEN CC 的 **DojoLightingBg**（键盘代号 Dojo）里，
  它把热键事件(0x1B)映射成模式并重放灯效，写灯走 EC 邮箱。

## 已知问题：亮度只有两段（灭/亮），三档亮度待逆向

实测结论（2026-08-10，Dojo 四分区键盘）：

- 邮箱载荷（CMDT 0x0B）的亮度字节 `[3]`：**0=灭、1=灭、50=低亮、100=满亮**
  （用户实机确认，并非全满亮）；2-49 之间的取值未确认。
- LBRT（CMDT 0x05，`0x64`=关 / `0xE4`=开）**单独写入无可视效果**；
  但每次亮度切换前写一次 LBRT 会让随后的邮箱亮度字节生效
  （不写则 50↔100 这类同开状态间的切换会被 EC 忽略）。
- 开档之间（50↔100）的切换仍不稳定：从灭态写入可生效，
  但从某一开档直接切到另一开档时，EC 有时会忽略新亮度。
- OGH 的三档亮度（关/低/高）来自键盘 EC 自身的 Fn 快捷键状态机，
  当前 WMI ABI（DSDT LM03/LM04/LM05）没有暴露中间档的控制位，
  待继续逆向 DojoLightingBg 的动画/亮度载荷或 EC 固件。

因此 GUI 暂提供 **关 / 开** 两段式；CLI `brightness 0-100` 仍可任意传值，
其中 50=低亮、100=满亮。

## 权限
- Windows 分区保持只读挂载；提取的 DLL 在 /tmp/omenwin（可删）。
- 用户临时密码请尽快改回。
