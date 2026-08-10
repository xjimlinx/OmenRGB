//! LightBarCmdByte 载荷构造（DojoLightingBg 逆向）。

use crate::{DEVICE_KEYBOARD, MODE_STATIC};

pub const LBB_DEVICE: usize = 0;
pub const LBB_MODE: usize = 1;
pub const LBB_BRIGHTNESS: usize = 3;
pub const LBB_COLOR_COUNT: usize = 6;
pub const LBB_ZONE_RGB: usize = 7;
pub const COLOR_TABLE_OFFSET: usize = 0x19;

fn rgb_bytes(rgb: &str) -> Result<[u8; 3], String> {
    let rgb = rgb.trim().trim_start_matches('#');
    if rgb.len() != 6 || !rgb.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(format!("颜色必须是 6 位十六进制 RRGGBB: {rgb}"));
    }
    let r = u8::from_str_radix(&rgb[0..2], 16).unwrap();
    let g = u8::from_str_radix(&rgb[2..4], 16).unwrap();
    let b = u8::from_str_radix(&rgb[4..6], 16).unwrap();
    Ok([r, g, b])
}

/// 构造 128 字节键盘灯效命令（WMI 0x20009 CMDT 0x0B 载荷）。
pub fn lightbar_payload(
    colors: &[String; 4],
    mode: u8,
    brightness: u8,
    device: u8,
) -> Result<[u8; 128], String> {
    let mut p = [0u8; 128];
    p[LBB_DEVICE] = device;
    p[LBB_MODE] = mode;
    p[LBB_BRIGHTNESS] = brightness;
    p[LBB_COLOR_COUNT] = 4;
    for (i, c) in colors.iter().enumerate() {
        let [r, g, b] = rgb_bytes(c)?;
        let off = LBB_ZONE_RGB + i * 3;
        p[off] = r;
        p[off + 1] = g;
        p[off + 2] = b;
    }
    Ok(p)
}

/// 传统 BIOS/开机颜色表（WMI CMDT 0x03，颜色在偏移 0x19）。
pub fn legacy_color_table(colors: &[String; 4]) -> Result<[u8; 128], String> {
    let mut p = [0u8; 128];
    for (i, c) in colors.iter().enumerate() {
        let [r, g, b] = rgb_bytes(c)?;
        let off = COLOR_TABLE_OFFSET + i * 3;
        p[off] = r;
        p[off + 1] = g;
        p[off + 2] = b;
    }
    Ok(p)
}

/// 从 128 字节颜色表读出 4 区颜色（hex 字符串）。
pub fn zones_from_table(table: &[u8]) -> Vec<String> {
    (0..4)
        .map(|i| {
            let off = COLOR_TABLE_OFFSET + i * 3;
            format!(
                "{:02X}{:02X}{:02X}",
                table[off],
                table[off + 1],
                table[off + 2]
            )
        })
        .collect()
}

pub fn static_payload(colors: &[String; 4], brightness: u8) -> Result<[u8; 128], String> {
    lightbar_payload(colors, MODE_STATIC, brightness, DEVICE_KEYBOARD)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn static_payload_layout() {
        let colors = [
            "FF0000".to_string(),
            "00FF00".to_string(),
            "0000FF".to_string(),
            "FFFFFF".to_string(),
        ];
        let p = static_payload(&colors, 100).unwrap();
        assert_eq!(p[0], 1);
        assert_eq!(p[1], 0);
        assert_eq!(p[3], 100);
        assert_eq!(p[6], 4);
        assert_eq!(&p[7..10], &[0xFF, 0x00, 0x00]);
        assert_eq!(&p[10..13], &[0x00, 0xFF, 0x00]);
        assert_eq!(&p[13..16], &[0x00, 0x00, 0xFF]);
        assert_eq!(&p[16..19], &[0xFF, 0xFF, 0xFF]);
    }

    #[test]
    fn bad_color_rejected() {
        let colors = [
            "12345".to_string(),
            "00FF00".to_string(),
            "0000FF".to_string(),
            "FFFFFF".to_string(),
        ];
        assert!(static_payload(&colors, 100).is_err());
    }
}
