# 版权与分发分析（OGH 逆向相关）

## 1. 结论速览

| 内容 | 能否公开 |
|------|----------|
| OGH 的 DLL（DojoLightingBg、FourZone 等） | ❌ 不能（专有二进制） |
| OGH 提取的图片/GIF/BAML/JSON 素材 | ❌ 不建议（衍生复制品） |
| WMI 协议、载荷布局、动画 mode 映射、分区坐标等**事实** | ✅ 可以 |
| 逆向**思路/过程/技巧**的文字描述 | ✅ 可以 |
| 本项目自写的代码、图标、文档 | ✅ 可以 |

## 2. 法律层面的判断（非律师意见）

### 2.1 二进制与素材

- HP/OGH 的 DLL、PNG、GIF、BAML、内部 JSON 均受版权保护。
- 复制并分发（即使改个名、放进开源仓库）构成对复制权的侵犯；
  `include_bytes!` 进二进制随源码分发同样属于复制。
- 提取素材用于**个人互操作研究**是常见做法，但**公开分发**是另一回事。

### 2.2 协议事实

- 接口、字节布局、命令码、枚举值属于"事实/功能信息"，本身不受版权保护
  （与 API 互操作相关的事实性内容）。
- 用文字描述这些事实（本文档、REVERSE_ENGINEERING.md）通常没有问题，
  建议注明来源"通过分析 OGH 与 DSDT 获得"。

### 2.3 反向工程本身

- 多数司法辖区允许为互操作性目的进行反向工程；用户是设备的合法拥有者，
  提取自其自己安装的软件。风险主要在**再分发**，而非研究。
- EULA 可能限制反编译/反向工程；实践中互操作性研究风险较低，但值得知晓。

## 3. 当前仓库状态（需要处理）

以下文件是从 OGH 提取的素材，已随仓库推送到 GitHub（公开）：

```
assets/ogh/*            （外框/键盘底图/pre_*.gif/dojo_zone_map.json/kbkeys.json）
assets/keyboards/ogh_real/*
assets/keyboards/dragon-*  assets/keyboards/accessory-*
assets/keyboards/4zone-*.png
rust/omenrgb-gui/assets/kbkeyboard-gamora.png
rust/omenrgb-gui/assets/dojo-zones.json
```

其中 `kbkeyboard-gamora.png` 与 `dojo-zones.json` 被 GUI 编译期引用
（`include_bytes!`），移除需要先替换实现。

## 4. 建议方案

### 方案 A：仓库转私有（推荐，零改动）

- `gh repo edit xjimlinx/OmenRGB --visibility private`
- 全部保留，功能不受影响；只对协作者可见，避免公开分发问题。
- 以后想公开时再处理素材。

### 方案 B：保持公开 + 移除 OGH 素材

- 从 git 移除上述素材（保留在本地 `.re/`）。
- GUI 键盘底图需替换为自绘/授权素材（可参考 OGH 外观重绘，本项目已会画）。
- `dojo-zones.json`（分区坐标）属于功能数据，可保留或改写为自产格式。

### 已执行的安全措施

- 所有 DLL/素材/脚本/IL 输出已持久化到 **`.re/`**（gitignore，不会推送）。
- 逆向过程笔记 `docs/REVERSE_ENGINEERING.md` 只含事实与思路，可安全公开。
