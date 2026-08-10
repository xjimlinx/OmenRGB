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
pub const CMDT_SET_BRIGHTNESS: u32 = 0x05;
pub const CMDT_GET_KEYBOARD_TYPE: u32 = 0x2B;

pub const DEVICE_KEYBOARD: u8 = 1; // TargetDevice::FourZoneAni
pub const MODE_STATIC: u8 = 0;

/// 动画模式：内部名、载荷 mode 字节、英文显示名、中文显示名。
/// 逆向自 HP.Omen.Core.Model.DataStructure 的 FourZoneAni.AnimationEffect 枚举
/// 与 DojoLightingBg DojoLightingWmiHelperV2._effectMapping：
///   ColorCycle=0→4→2、Starlight=1→5→3、Breathing=2→6→4、Wave=3→7→6、
///   Raindrop=4→8→7、AudioPulse=5→9→8、Confetti=6→10→9、Sun=7→11→10、
///   Swipe=8→12→11。
pub const ANIMATION_MODES: &[(&str, u8, &str, &str)] = &[
    ("colorcycle", 2, "Color Cycle", "颜色循环"),
    ("starlight", 3, "Starlight", "星光"),
    ("breathing", 4, "Breathing", "呼吸"),
    ("wave", 6, "Wave", "波浪"),
    ("raindrop", 7, "Raindrop", "雨滴"),
    ("audiopulse", 8, "Audio Pulse", "声波律动"),
    ("confetti", 9, "Confetti", "彩纸"),
    ("sun", 10, "Sun", "太阳"),
    ("swipe", 11, "Swipe", "滑动"),
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
