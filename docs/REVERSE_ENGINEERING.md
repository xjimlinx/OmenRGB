# HP OMEN 键盘灯控逆向笔记

> 本文只记录**事实、协议与思路**，不包含 HP/OGH 专有二进制或受版权保护的素材。
> 专有文件保存在本地 `.re/`（gitignore），详见 [COPYRIGHT.md](COPYRIGHT.md)。

## 1. 目标

在 Linux 上控制 HP OMEN 16（键盘代号 **Dojo**）的四分区 RGB 键盘：

- 读取/写入 4 个分区颜色
- 切换动画（ColorCycle / Starlight / Breathing / Wave / Raindrop / AudioPulse / …）
- 控制亮度
- 状态回读（当前模式 KBAM、颜色、亮度）

## 2. 素材来源

1. **本机 DSDT 反汇编**（`research/aml/DSDT.dsl`）：确定 WMI 入口
   `\_SB.WMID.WMAA`、命令分派（0x20008 Gaming / 0x20009 背光）、EC 字段
   （LRGB/BRGB/LBRT/LCMC/KBAM 等）。
2. **主线内核补丁**（`research/hp-wmi-multicolor-v10.patch`）：对照 ABI 命名，
   确认 0x64=关 / 0xE4=开等约定。
3. **OGH Windows 安装目录**（只读挂载）：提取全部 DLL、BAML、图片、JSON。
4. **网络检索**：KDE Wayland 图标匹配规则、HP 服务手册（Fn 锁定）等。

## 3. 工具链

| 工具 | 用途 |
|------|------|
| `dnfile` + `dncil` | 直接读 .NET 元数据 + CIL 字节码（无需完整反编译器） |
| `extract_res.py` | 从 DLL 提取 .NET 资源（BAML/图片/JSON） |
| `baml2.py` | BAML → XAML 文本 |
| `strings` | 快速定位关键字（类名/字段名/日志串） |
| dnfile 自写辅助脚本 | 枚举 TypeDef/方法/字段常量/调用点交叉引用 |

## 4. 逆向流程与思路

### 4.1 先找"谁在管灯"

在几十个 DLL 里定位键盘灯效实现：

1. `strings` 全量扫关键词：`Keyboard`、`Lighting`、`Wmi`、`Backlight`、
   `Brightness`、`FourZone`。
2. 命名即线索：`HP.Omen.Background.DojoLightingBg.dll` 的名字里带 **Dojo**
   （键盘代号，从机型服务手册/固件字符串确认），且方法名直白：
   `BiosLightBarWmiCmd_*`、`LightBarCmdByte`。
3. 用字符串里的 `_effectMapping`、`KbBacklitBrightness` 交叉确认这就是真身，
   而不是 OGH 里给其他机型用的旧模块。

### 4.2 从 async 状态机还原载荷构造

C# `async` 方法编译成 `<Method>d__N::MoveNext` 状态机，逻辑都在 MoveNext 里：

1. 先 dump `TypeName::Method` 的壳（参数列表、字段赋值），拿到参数名和顺序。
2. 再 dump `<Method>d__N::MoveNext`，按 IL 指令把 `newarr 128` 后的
   `ldc.i4.k; ldfld; stelem.i1` 序列逐字节还原成载荷布局。
3. 用 token 解析器把 `0x040000XX`（字段）、`0x060000XX`（方法）、
   `0x0A0000XX`（成员引用）翻译成名字，IL 可读性大增。

以 `<BiosLightBarWmiCmd_SetLightColor>d__10::MoveNext` 为例：

```text
arr[1] = 0              ; MODE=0 静态
arr[3] = brightness     ; BRIGHTNESS
arr[6] = 4              ; COLOR_COUNT
arr[7..18] = 4×RGB      ; ZONE1..4
```

`LightBarCmdByte` 枚举常量值（DEVICE=0, MODE=1, CONFIG=2, BRIGHTNESS=3,
TRIBE=4, BASS=5, COLOR_COUNT=6, ZONE1_RGB_R=7 …）与上面的偏移完全吻合。

### 4.3 枚举常量读取

枚举字面量存在 Constant 表，用 Parent → Field 关联：

```python
for c in mdt.Constant.rows:
    parent = c.Parent            # MDTableIndex
    if parent.table.name == 'Field':
        print(parent.row_index, c.Value.value)
```

由此得到 `KbBacklitBrightness`：OFF=0, 1ST=1, 2ND=2；
`LightBarCmdByte` 全部字段值；动画 effect→mode 映射表。

### 4.4 交叉引用找调用链

扫描所有方法体的 CIL，找 `call/callvirt` token 指向目标方法，还原
"热键 → 配置 → 灯效重放" 的完整链路（如 `ReceiveWmiHotKey` → 改配置 →
`SetStaticColorAsync`）。

### 4.5 实测验证（关键）

逆向给出的协议必须在真机上验证。本项目采用：

- 守护进程暴露诊断命令（如 `lbrt <字节>`、`brightness <0-100>`），
  通过 socket 免 sudo 下发，实时看键盘反应。
- GUI 调试按钮（临时）让用户在自己节奏下 A/B 对比。
- 每轮结论记入本文档与 `LINUX_RGB_STATUS.md`，区分"逆向推断"与"实机确认"。

## 5. 已确认的协议

### 5.1 WMI 调用

```
\_SB.WMID.WMAA 0 <mid> b<hex>
```

| 偏移 | 长度 | 内容 |
|------|------|------|
| 0x00 | 4 | 签名 "SECU" (0x55434553) |
| 0x04 | 4 | COMD：0x00020009 背光 / 0x00020008 Gaming |
| 0x08 | 4 | CMDT |
| 0x0C | 4 | 载荷长度 |
| 0x10 | N | 载荷 |

| COMD | CMDT | 功能 | outsize |
|------|------|------|--------|
| 0x20009 | 0x01 | 读能力 | 4 |
| 0x20009 | 0x02 | 读颜色表（128B） | 128 |
| 0x20009 | 0x03 | 写颜色表（RGB 在 0x19） | 128 |
| 0x20009 | 0x04 | 读亮度（LBRT） | 4 |
| 0x20009 | 0x05 | 写亮度（1 字节） | 1 |
| 0x20009 | 0x0B | 实时灯效邮箱（128B LightBarCmdByte） | 8 |
| 0x20008 | 0x2B | 读键盘类型（RE20） | 4 |

### 5.2 LightBarCmdByte（128 字节）

| 偏移 | 字段 |
|------|------|
| 0 | DEVICE（键盘=1） |
| 1 | MODE（0=静态，2..11=动画） |
| 2 | CONFIG（位打包：effect/speed/theme） |
| 3 | BRIGHTNESS（0=灭，50=低，100=满） |
| 4 | TRIBE_INTENSITY |
| 5 | BASS_INTENSITY |
| 6 | COLOR_COUNT（=4） |
| 7..18 | ZONE1-4 RGB |

### 5.3 动画 mode 映射（FourZoneAni 枚举 → effect → 载荷字节）

| 内部名 | 载荷字节 |
|--------|----------|
| colorcycle | 2 |
| starlight | 3 |
| breathing | 4 |
| wave | 6 |
| raindrop | 7 |
| audiopulse | 8 |
| confetti | 9 |
| sun | 10 |
| swipe | 11 |

### 5.4 亮度实测结论（2026-08-10）

- 邮箱亮度字节：**0=灭、1=灭、50=低亮、100=满亮**；2-49 未确认。
- LBRT（0x05）单独写入无可视效果；但每次亮度切换前写一次
  （0x64=关 / 0xE4=开）可让随后的邮箱亮度字节生效。
- 开档之间（50↔100）直接切换不稳定，从灭态写入最可靠。
- 三档亮度在 OGH 里来自键盘 EC 自身的 Fn 状态机，当前 WMI ABI 未暴露中间档控制位。

## 6. 分区几何数据

DojoUS.json（OGH FourZone 模块）提供逐键光区矩形：

- zone0 = 右侧 + 小键盘（32 键）
- zone1 = 中间（37 键）
- zone2 = 左侧（22 键，不含 Q/E/R/F）
- zone3 = QWER/ASDF（8 键，本机实机为 QWER/ASDF 而非 WASD）

GUI 渲染时 area→hw zone 映射为 `3 - area`。

## 7. 待办/未知

- 三档亮度中间档的 EC 控制位（可能藏在 EC 固件或未公开 WMI 子命令）。
- 动画 CONFIG 位（速度/方向/主题）完整解码。
- 开机（BIOS）灯持久化颜色写入已实现（CMDT 0x03），重启后由 EC 接管，
  与 OGH 行为是否一致待验证。
