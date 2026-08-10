//! OMEN RGB 键盘灯效核心库。
//!
//! 协议来自对 Windows OMEN CC（DojoLightingBg）的逆向：
//! 实时灯效走 WMI 0x20009 CMDT 0x0B（EC 邮箱）+ LightBarCmdByte 载荷。

pub mod backend;
pub mod client;
pub mod kbam;
pub mod payload;
pub mod proto;
pub mod wmi;

pub const CMD_BACKLIGHT: u32 = 0x0002_0009;
pub const CMDT_LIGHTBAR_MAILBOX: u32 = 0x0B;
pub const CMDT_SET_COLOR: u32 = 0x03;
pub const CMDT_GET_COLOR: u32 = 0x02;
pub const CMDT_GET_BRIGHTNESS: u32 = 0x04;
pub const CMDT_GET_KEYBOARD_TYPE: u32 = 0x2B;

pub const DEVICE_KEYBOARD: u8 = 1; // TargetDevice::FourZoneAni
pub const MODE_STATIC: u8 = 0;

/// 动画模式：内部名、载荷 mode 字节、英文显示名、中文显示名。
/// mode 字节来自 DojoLightingBg `_effectMapping`（4→2 … 12→11）；
/// 显示名对照 OMEN CC（DragonLightingModule / McuSDK2）的枚举与文案。
/// 注意：mode 与具体动画的对应关系待实机逐项确认（见 README）。
pub const ANIMATION_MODES: &[(&str, u8, &str, &str)] = &[
    ("ghosting", 2, "Ghosting", "幽灵"),
    ("ripple", 3, "Ripple", "涟漪"),
    ("wave", 4, "Wave", "波浪"),
    ("omenx", 6, "OMEN X", "OMEN X"),
    ("raindrop", 7, "Raindrop", "雨滴"),
    ("audiopulse", 8, "Audio Pulse", "声波律动"),
    ("linestreak", 9, "Line Streak", "线条"),
    ("starlight", 10, "Starlight", "星光"),
    ("galaxy", 11, "Galaxy", "银河"),
];

pub fn animation_mode_byte(name: &str) -> Option<u8> {
    ANIMATION_MODES.iter().find(|(n, ..)| *n == name).map(|(_, b, ..)| *b)
}

pub fn animation_display_name(name: &str) -> (&str, &str) {
    ANIMATION_MODES
        .iter()
        .find(|(n, ..)| *n == name)
        .map(|(_, _, en, cn)| (*en, *cn))
        .unwrap_or((name, name))
}

/// 分区名按硬件实际顺序（实机验证）：
/// 0=QWER/ASDF 核心小区、1=左侧、2=中间、3=右侧+小键盘。
pub const ZONE_NAMES: [&str; 4] = ["QWER/ASDF", "左侧", "中间", "右侧+小键盘"];
