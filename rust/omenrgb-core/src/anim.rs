//! 主机驱动的四分区自定义动画。
//!
//! 固件预置动画只能选 MODE，自定义动画走另一条路：守护进程按帧率
//! 循环写「静态色」载荷（MODE=0），由主机逐帧计算四个分区的颜色。
//! 每帧只占用 128 字节邮箱 + 一次 WMI 调用，内存/CPU 开销可忽略。

/// 自定义动画定义：内部名、中文名、描述。
pub struct CustomAnim {
    pub name: &'static str,
    pub label_cn: &'static str,
    pub desc: &'static str,
}

/// 常规四分区动画（主机驱动）。
pub const CUSTOM_ANIMS: &[CustomAnim] = &[
    CustomAnim { name: "breath", label_cn: "呼吸", desc: "四区同步明暗呼吸" },
    CustomAnim { name: "wave", label_cn: "波浪", desc: "明暗波依次扫过四区" },
    CustomAnim { name: "rainbow", label_cn: "彩虹循环", desc: "全键盘色调同步循环" },
    CustomAnim { name: "flow", label_cn: "流动彩虹", desc: "彩虹按分区顺序流动" },
    CustomAnim { name: "chase", label_cn: "跑马灯", desc: "高亮点依次扫过四区" },
    CustomAnim { name: "strobe", label_cn: "闪烁", desc: "快速开关闪烁" },
    CustomAnim { name: "heartbeat", label_cn: "心跳", desc: "双脉冲心跳律动" },
    CustomAnim { name: "twinkle", label_cn: "星光", desc: "分区随机明暗闪烁" },
];

pub fn custom_anim_names() -> Vec<&'static str> {
    CUSTOM_ANIMS.iter().map(|a| a.name).collect()
}

pub fn custom_anim_label<'a>(name: &'a str) -> &'a str {
    CUSTOM_ANIMS
        .iter()
        .find(|a| a.name == name)
        .map(|a| a.label_cn)
        .unwrap_or(name)
}

pub fn custom_anim_desc<'a>(name: &'a str) -> &'a str {
    CUSTOM_ANIMS
        .iter()
        .find(|a| a.name == name)
        .map(|a| a.desc)
        .unwrap_or("")
}

/// 纯色 HSL→RGB（用于彩虹类动画；h∈[0,360)，s/l∈[0,1]）。
fn hsl(h: f32, s: f32, l: f32) -> [u8; 3] {
    let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let hp = (h.rem_euclid(360.0)) / 60.0;
    let x = c * (1.0 - (hp % 2.0 - 1.0).abs());
    let (r, g, b) = match hp as i32 {
        0 => (c, x, 0.0),
        1 => (x, c, 0.0),
        2 => (0.0, c, x),
        3 => (0.0, x, c),
        4 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    let m = l - c / 2.0;
    [
        ((r + m) * 255.0).clamp(0.0, 255.0) as u8,
        ((g + m) * 255.0).clamp(0.0, 255.0) as u8,
        ((b + m) * 255.0).clamp(0.0, 255.0) as u8,
    ]
}

/// 把基础色按系数缩放（呼吸/波浪/心跳等明暗类动画用）。
fn scale(base: [u8; 3], f: f32) -> [u8; 3] {
    let f = f.clamp(0.0, 1.0);
    [
        (base[0] as f32 * f) as u8,
        (base[1] as f32 * f) as u8,
        (base[2] as f32 * f) as u8,
    ]
}

/// 简易确定性伪随机（twinkle 用）：0..n
fn hash(i: usize, k: usize) -> u32 {
    let mut x = (i as u32).wrapping_mul(0x9E37_79B9) ^ (k as u32).wrapping_mul(0x85EB_CA6B);
    x = (x ^ (x >> 15)).wrapping_mul(0x2C1B_3C6D);
    x ^ (x >> 12)
}

/// 计算动画在 t 秒时的四区颜色（硬件分区顺序 0..3）。
///
/// - `base`：明暗类动画的基础色（RGB）。
/// - `speed`：倍速，1.0 = 常规。
pub fn custom_anim_frame(name: &str, t: f32, base: [u8; 3], speed: f32) -> [[u8; 3]; 4] {
    let t = t * speed.max(0.05);
    match name {
        "breath" => {
            let f = (t * std::f32::consts::TAU).sin() * 0.5 + 0.5;
            let f = 0.12 + 0.88 * f;
            [scale(base, f); 4]
        }
        "wave" => {
            (0..4)
                .map(|i| {
                    let f = (t * std::f32::consts::TAU - i as f32 * std::f32::consts::FRAC_PI_2)
                        .sin()
                        * 0.5
                        + 0.5;
                    scale(base, 0.10 + 0.90 * f)
                })
                .collect::<Vec<_>>()
                .try_into()
                .unwrap()
        }
        "rainbow" => {
            let c = hsl(t * 60.0, 1.0, 0.5);
            [c; 4]
        }
        "flow" => (0..4)
            .map(|i| hsl(t * 60.0 + i as f32 * 90.0, 1.0, 0.5))
            .collect::<Vec<_>>()
            .try_into()
            .unwrap(),
        "chase" => (0..4)
            .map(|i| {
                // 窄高亮窗依次扫过：cos^8 形状
                let ph = t * std::f32::consts::TAU - i as f32 * std::f32::consts::FRAC_PI_2;
                let f = ph.cos().max(0.0).powi(8);
                scale(base, 0.08 + 0.92 * f)
            })
            .collect::<Vec<_>>()
            .try_into()
            .unwrap(),
        "strobe" => {
            let on = (t * 2.0).fract() < 0.5;
            [scale(base, if on { 1.0 } else { 0.08 }); 4]
        }
        "heartbeat" => {
            // 经典双脉冲：主搏 + 次搏
            let tm = t.rem_euclid(1.2);
            let e1 = (-((tm - 0.12).powi(2)) / 0.004).exp();
            let e2 = 0.65 * (-((tm - 0.30).powi(2)) / 0.006).exp();
            let f = (e1 + e2).clamp(0.0, 1.0);
            [scale(base, 0.10 + 0.90 * f); 4]
        }
        "twinkle" => (0..4)
            .map(|i| {
                let k = (t * 3.0) as usize;
                let r = hash(i, k) % 5;
                let on = if r == 0 { 1.0 } else if r == 1 { 0.55 } else { 0.10 };
                scale(base, on)
            })
            .collect::<Vec<_>>()
            .try_into()
            .unwrap(),
        _ => [base; 4],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn breath_starts_dim_and_cycles() {
        let base = [255, 0, 0];
        let f0 = custom_anim_frame("breath", 0.0, base, 1.0);
        let fq = custom_anim_frame("breath", 0.25, base, 1.0); // 半周期
        assert_eq!(f0.len(), 4);
        // t=0 时 sin=0 → f=0.56，中等偏暗；不会瞬间满亮
        assert!(f0[0][0] < 255);
        // 不同时刻帧不同
        assert_ne!(f0, fq);
    }

    #[test]
    fn wave_zone_phase_offsets() {
        let base = [0, 255, 0];
        let a = custom_anim_frame("wave", 0.0, base, 1.0);
        let b = custom_anim_frame("wave", 0.125, base, 1.0);
        assert_ne!(a[0], b[0]);
        assert!(a.iter().all(|c| c[1] <= 255 && c[2] == 0));
    }

    #[test]
    fn rainbow_is_hue_rotation() {
        let c0 = custom_anim_frame("rainbow", 0.0, [0, 0, 0], 1.0);
        let c1 = custom_anim_frame("rainbow", 1.0, [0, 0, 0], 1.0);
        assert_eq!(c0[0], [255, 0, 0]); // 0° 纯红
        assert_ne!(c0[0], c1[0]); // 60° 后不同
    }

    #[test]
    fn unknown_name_falls_back_to_base() {
        assert_eq!(custom_anim_frame("nope", 3.2, [1, 2, 3], 1.0), [[1, 2, 3]; 4]);
    }

    #[test]
    fn all_colors_in_range() {
        for a in CUSTOM_ANIMS {
            for k in 0..60 {
                let t = k as f32 / 30.0;
                for c in custom_anim_frame(a.name, t, [255, 128, 64], 1.2) {
                    assert!(c.iter().all(|&v| v <= 255));
                }
            }
        }
    }
}
