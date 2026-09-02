//! OMEN RGB 键盘控制器 — egui 深色游戏风 GUI（经守护进程读写）。

use eframe::egui::{self, Color32, FontId, Pos2, Rect, RichText, Stroke, StrokeKind, TextureHandle, Vec2};
use omenrgb_core::anim::{custom_anim_desc, custom_anim_label, CUSTOM_ANIMS};
use omenrgb_core::client::Client;
use omenrgb_core::animation_display_name;
use omenrgb_core::ZONE_NAMES;
use ksni::TrayMethods;
use std::io::{BufReader, Cursor, Write};
use std::os::unix::io::AsRawFd;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// OMEN 风格深色主题：暖黑背景 + 图标同款红粉主色（#FF2C74 → #FF6A3D 渐变系）
const BG: Color32 = Color32::from_rgb(0x10, 0x11, 0x16);
const PANEL: Color32 = Color32::from_rgb(0x19, 0x1A, 0x22);
const PANEL2: Color32 = Color32::from_rgb(0x22, 0x23, 0x2E);
const TEXT: Color32 = Color32::from_rgb(0xF0, 0xF1, 0xF6);
const MUTED: Color32 = Color32::from_rgb(0x9C, 0x9D, 0xA8);
const ACCENT: Color32 = Color32::from_rgb(0xFF, 0x2C, 0x74);
const OK: Color32 = Color32::from_rgb(0x4C, 0xC3, 0x8A);
const ERR: Color32 = Color32::from_rgb(0xFF, 0x4D, 0x4F);

/// 从本机 OGH「键盘灯-无色」截图量出的键帽面几何，坐标相对 884×316 外框。
/// 仅记录几何事实；实际外框和每个键帽都在运行时自行绘制。
const OMEN16_KEY_RECTS: &[[f32; 4]] = &[
    [33.0, 29.0, 35.0, 27.0], [76.0, 29.0, 34.0, 27.0], [120.0, 29.0, 34.0, 27.0], [164.0, 29.0, 34.0, 27.0], [208.0, 29.0, 34.0, 27.0], [252.0, 29.0, 34.0, 27.0], [294.0, 29.0, 35.0, 27.0], [337.0, 29.0, 35.0, 27.0], [380.0, 29.0, 34.0, 27.0], [422.0, 29.0, 35.0, 27.0], [465.0, 29.0, 35.0, 27.0], [508.0, 29.0, 34.0, 27.0], [551.0, 29.0, 34.0, 27.0], [595.0, 29.0, 34.0, 27.0], [636.0, 29.0, 34.0, 27.0], [677.0, 29.0, 37.0, 27.0], [723.0, 29.0, 37.0, 27.0], [768.0, 29.0, 37.0, 27.0], [813.0, 29.0, 37.0, 27.0],
    [34.0, 63.0, 31.0, 37.0], [73.0, 63.0, 37.0, 37.0], [118.0, 63.0, 38.0, 37.0], [164.0, 63.0, 37.0, 37.0], [209.0, 63.0, 37.0, 37.0], [254.0, 63.0, 38.0, 37.0], [300.0, 63.0, 37.0, 37.0], [345.0, 63.0, 37.0, 37.0], [390.0, 63.0, 38.0, 37.0], [436.0, 63.0, 37.0, 37.0], [481.0, 63.0, 37.0, 37.0], [527.0, 63.0, 37.0, 37.0], [572.0, 63.0, 37.0, 37.0], [617.0, 63.0, 53.0, 37.0], [677.0, 63.0, 37.0, 37.0], [723.0, 63.0, 37.0, 37.0], [768.0, 63.0, 37.0, 37.0], [813.0, 63.0, 37.0, 37.0],
    [34.0, 107.0, 54.0, 37.0], [96.0, 107.0, 37.0, 37.0], [141.0, 107.0, 37.0, 37.0], [186.0, 107.0, 38.0, 37.0], [232.0, 107.0, 37.0, 37.0], [277.0, 107.0, 37.0, 37.0], [322.0, 107.0, 38.0, 37.0], [368.0, 107.0, 37.0, 37.0], [413.0, 107.0, 37.0, 37.0], [458.0, 107.0, 38.0, 37.0], [504.0, 107.0, 37.0, 37.0], [549.0, 107.0, 37.0, 37.0], [593.0, 107.0, 36.0, 37.0], [636.0, 107.0, 34.0, 37.0], [677.0, 107.0, 37.0, 37.0], [723.0, 107.0, 37.0, 37.0], [768.0, 107.0, 37.0, 37.0], [813.0, 107.0, 37.0, 82.0],
    [34.0, 151.0, 60.0, 37.0], [102.0, 151.0, 38.0, 37.0], [148.0, 151.0, 37.0, 37.0], [193.0, 151.0, 37.0, 37.0], [238.0, 151.0, 38.0, 37.0], [284.0, 151.0, 37.0, 37.0], [329.0, 151.0, 37.0, 37.0], [374.0, 151.0, 38.0, 37.0], [420.0, 151.0, 37.0, 37.0], [465.0, 151.0, 37.0, 37.0], [511.0, 151.0, 37.0, 37.0], [556.0, 151.0, 37.0, 37.0], [601.0, 151.0, 69.0, 37.0], [677.0, 151.0, 37.0, 37.0], [723.0, 151.0, 37.0, 37.0], [768.0, 151.0, 37.0, 37.0],
    [34.0, 195.0, 84.0, 37.0], [126.0, 195.0, 38.0, 37.0], [172.0, 195.0, 37.0, 37.0], [217.0, 195.0, 37.0, 37.0], [262.0, 195.0, 38.0, 37.0], [308.0, 195.0, 37.0, 37.0], [353.0, 195.0, 37.0, 37.0], [398.0, 195.0, 38.0, 37.0], [444.0, 195.0, 37.0, 37.0], [489.0, 195.0, 37.0, 37.0], [535.0, 195.0, 37.0, 37.0], [580.0, 195.0, 44.0, 37.0], [632.0, 195.0, 37.0, 37.0], [677.0, 195.0, 37.0, 37.0], [723.0, 195.0, 37.0, 37.0], [768.0, 195.0, 37.0, 37.0], [813.0, 195.0, 37.0, 82.0],
    [34.0, 239.0, 38.0, 37.0], [80.0, 239.0, 37.0, 37.0], [125.0, 239.0, 37.0, 37.0], [170.0, 239.0, 38.0, 37.0], [216.0, 240.0, 220.0, 37.0], [444.0, 240.0, 37.0, 37.0], [489.0, 240.0, 37.0, 37.0], [535.0, 240.0, 43.0, 37.0], [587.0, 240.0, 37.0, 37.0], [632.0, 240.0, 37.0, 37.0], [677.0, 240.0, 37.0, 37.0], [723.0, 240.0, 37.0, 37.0], [768.0, 240.0, 37.0, 37.0],
];

/// 预选颜色（按色系分组）。含从 Windows OGH 逆向提取的原生色
/// （FourZoneModule.dll / 配置 JSON：#FF0F36 红、#FF710F 橙、#FFFF00/#FFF935 黄、
///  #0FFA36 绿、#0F36FA 蓝、#FF0F84 粉、#FF0FFA 品红、#FA0FE7 紫）。
const PRESET_GROUPS: &[(&str, &[&str])] = &[
    (
        "黑白灰",
        &[
            "000000", "3A3A3C", "636366", "8E8E93", "C7C7CC", "E5E5EA", "FFFFFF",
        ],
    ),
    (
        "红粉",
        &[
            "FF0000", "FF3B30", "DC143C", "FF0F36", "FF2D55", "FF6482", "FF1493", "FF69B4",
            "FF0F84",
        ],
    ),
    (
        "橙黄棕",
        &[
            "FF4500", "FF9500", "FF710F", "FFF935", "FFCC00", "FFD60A", "FFFF00", "FFA500",
            "D2691E", "8B4513",
        ],
    ),
    (
        "绿青",
        &[
            "0FFA36", "00FF00", "32CD32", "34C759", "30D158", "008000", "2E8B57", "00C7BE",
            "00CED1", "008080",
        ],
    ),
    (
        "蓝",
        &[
            "007AFF", "0F36FA", "0000FF", "000080", "4682B4", "87CEEB", "64D2FF", "00BFFF",
        ],
    ),
    (
        "紫品",
        &[
            "5856D6", "5E5CE6", "4B0082", "8A2BE2", "9400D3", "AF52DE", "BF5AF2", "FA0FE7",
            "FF00FF", "EE82EE",
        ],
    ),
];

const ANIMATIONS: [&str; 10] = [
    "静态", "colorcycle", "starlight", "breathing", "wave",
    "raindrop", "audiopulse", "confetti", "sun", "swipe",
];

/// 第二个实例通过 SIGUSR1 请求本实例显示主窗口。
static SHOW_REQUESTED: AtomicBool = AtomicBool::new(false);

extern "C" fn handle_show_signal(_sig: libc::c_int) {
    SHOW_REQUESTED.store(true, Ordering::Relaxed);
}

/// 单实例锁文件路径（优先 XDG_RUNTIME_DIR，避免 /tmp 被清理/权限问题）。
fn single_instance_lock_path() -> std::path::PathBuf {
    if let Some(dir) = std::env::var_os("XDG_RUNTIME_DIR") {
        std::path::PathBuf::from(dir).join("omenrgb-gui.lock")
    } else {
        std::path::PathBuf::from("/tmp/omenrgb-gui.lock")
    }
}

/// 单实例锁：成功返回持有锁的文件（main 生命周期内持有，进程退出自动释放）。
/// 失败（已有实例）则通知现有实例显示窗口并返回 None。
fn acquire_single_instance_lock() -> Option<std::fs::File> {
    let path = single_instance_lock_path();
    let file = std::fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(&path)
        .ok()?; // 打不开锁文件就不做强限制，避免影响正常使用
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc == 0 {
        let _ = file.set_len(0);
        let _ = (&file).write_all(format!("{}\n", std::process::id()).as_bytes());
        return Some(file);
    }
    let pid: i32 = std::fs::read_to_string(&path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    if pid > 0 {
        unsafe {
            libc::kill(pid, libc::SIGUSR1);
        }
    }
    let _ = std::process::Command::new("notify-send")
        .args([
            "-a",
            "OMEN RGB",
            "-i",
            "omenrgb",
            "OMEN RGB 已在运行",
            "已显示现有窗口，请勿重复打开",
        ])
        .status();
    eprintln!("[omenrgb-gui] 已有实例在运行（pid={pid}），已请求显示其窗口，本实例退出");
    None
}

/// 托盘菜单消息 → 主界面
enum TrayMsg {
    Show,
    Quit,
}

/// KDE/SNI 系统托盘（纯 Rust，无 GTK 依赖）
struct TrayApp {
    tx: mpsc::Sender<TrayMsg>,
    ctx: egui::Context,
}

impl ksni::Tray for TrayApp {
    fn id(&self) -> String {
        "omenrgb".into()
    }

    fn title(&self) -> String {
        "OMEN RGB 键盘控制器".into()
    }

    fn icon_pixmap(&self) -> Vec<ksni::Icon> {
        let bytes = include_bytes!("../../../icons/omenrgb-512.png");
        let Ok(img) = image::load_from_memory(bytes) else {
            return Vec::new();
        };
        let img = img.to_rgba8();
        let (w, h) = img.dimensions();
        // SNI 需要 ARGB32（网络字节序=大端），把 RGBA 转 ARGB
        let mut data = Vec::with_capacity((w * h * 4) as usize);
        for px in img.pixels() {
            data.extend_from_slice(&[px[3], px[0], px[1], px[2]]);
        }
        vec![ksni::Icon {
            width: w as i32,
            height: h as i32,
            data,
        }]
    }

    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        use ksni::menu::*;
        vec![
            StandardItem {
                label: "显示主界面".into(),
                activate: Box::new(|t: &mut Self| {
                    t.ctx.request_repaint(); // 立即唤醒事件循环，不等 500ms 轮询
                    let _ = t.tx.send(TrayMsg::Show);
                }),
                ..Default::default()
            }
            .into(),
            MenuItem::Separator,
            StandardItem {
                label: "退出".into(),
                activate: Box::new(|t: &mut Self| {
                    let _ = t.tx.send(TrayMsg::Quit);
                }),
                ..Default::default()
            }
            .into(),
        ]
    }
}

fn hex_to_color(s: &str) -> Color32 {
    let s = s.trim_start_matches('#');
    if s.len() != 6 {
        return Color32::WHITE;
    }
    let r = u8::from_str_radix(&s[0..2], 16).unwrap_or(0xFF);
    let g = u8::from_str_radix(&s[2..4], 16).unwrap_or(0xFF);
    let b = u8::from_str_radix(&s[4..6], 16).unwrap_or(0xFF);
    Color32::from_rgb(r, g, b)
}

/// HSL → RGB（S/L 取 0..1）。OGH 高级配色即 HSL(hue, 100%, bright/100)。
fn hsl_to_rgb(h: f32, s: f32, l: f32) -> [u8; 3] {
    let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let hp = (h.rem_euclid(360.0)) / 60.0;
    let x = c * (1.0 - (hp % 2.0 - 1.0).abs());
    let (r1, g1, b1) = match hp as i32 {
        0 => (c, x, 0.0),
        1 => (x, c, 0.0),
        2 => (0.0, c, x),
        3 => (0.0, x, c),
        4 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    let m = l - c / 2.0;
    [
        ((r1 + m) * 255.0).round() as u8,
        ((g1 + m) * 255.0).round() as u8,
        ((b1 + m) * 255.0).round() as u8,
    ]
}

/// 渐变滑条：自绘渐变底 + 拖拽调值（OGH 双条配色风格）。
fn gradient_slider(
    ui: &mut egui::Ui,
    value: &mut f32,
    min: f32,
    max: f32,
    sample: impl Fn(f32) -> Color32,
) -> egui::Response {
    let width = ui.available_width().min(240.0);
    let (rect, response) =
        ui.allocate_exact_size(Vec2::new(width, 16.0), egui::Sense::click_and_drag());
    if ui.is_rect_visible(rect) {
        let painter = ui.painter();
        let steps = 96;
        for i in 0..steps {
            let t0 = i as f32 / steps as f32;
            let t1 = (i + 1) as f32 / steps as f32;
            let r = Rect::from_min_max(
                Pos2::new(rect.left() + t0 * rect.width(), rect.top()),
                Pos2::new(rect.left() + t1 * rect.width(), rect.bottom()),
            );
            painter.rect_filled(r, 0.0, sample(t0));
        }
        painter.rect_stroke(
            rect,
            3.0,
            Stroke::new(1.0, Color32::from_gray(90)),
            egui::StrokeKind::Outside,
        );
        let t = ((*value - min) / (max - min)).clamp(0.0, 1.0);
        let cx = rect.left() + t * rect.width();
        let cy = rect.center().y;
        painter.circle_filled(Pos2::new(cx, cy), 7.0, Color32::WHITE);
        painter.circle_stroke(
            Pos2::new(cx, cy),
            7.0,
            Stroke::new(1.5, Color32::from_gray(30)),
        );
    }
    if response.dragged() || response.clicked() {
        if let Some(pos) = response.interact_pointer_pos() {
            let t = ((pos.x - rect.left()) / rect.width()).clamp(0.0, 1.0);
            *value = min + t * (max - min);
        }
    }
    response
}

struct App {
    client: Client,
    page: Page,
    // 四个分区的逐键光区；键盘外框和键帽均由本程序绘制。
    dojo_zones: Vec<Vec<[f32; 4]>>,
    zones: [String; 4],
    brightness: u8,
    selected: usize, // 0..3, 4 = all
    hex: String,
    animation: String,
    anim: Option<GifAnim>, // 当前动画的真实 OGH 预览
    status: String,
    status_color: Color32,
    initial_refresh: bool,
    profiles: Vec<(String, String, u8, String)>, // (名称, 颜色摘要, 亮度, 动画)
    profile_name: String,
    pick_hue: f32,
    pick_bright: f32,
    // 主机驱动自定义动画
    custom_running: Option<String>,
    custom_base: String,
    custom_speed: f32,
    hide_requested: bool,
    last_vid: Option<egui::ViewportId>,
    system: SystemStats,
    last_cpu_sample: Option<(u64, u64)>,
    last_net_sample: Option<(Instant, u64, u64)>,
    last_system_refresh: Instant,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Page {
    System,
    Lighting,
}

#[derive(Default)]
struct SystemStats {
    cpu_usage: f32,
    cpu_temp: Option<f32>,
    gpu_usage: Option<f32>,
    gpu_temp: Option<f32>,
    mem_used: u64,
    mem_total: u64,
    load: f32,
    process_count: usize,
    rx_rate: f64,
    tx_rate: f64,
    disks: Vec<DiskStat>,
}

struct DiskStat {
    mount: String,
    used: u64,
    total: u64,
}

/// dojo-zones.json 中的分区定义：4 个分区，每个分区若干 [X, Y, Width, Height] 光区
#[derive(serde::Deserialize)]
struct DojoZonesFile {
    zones: Vec<Vec<Vec<f32>>>,
}

/// GIF 预览播放器：流式解码当前动画帧。
struct GifAnim {
    bytes: Vec<u8>,
    iter: Option<gif::Decoder<BufReader<Cursor<Vec<u8>>>>>,
    tex: TextureHandle,
    delay_ms: f64,
    next_t: f64,
    w: usize,
    h: usize,
    canvas: Vec<u8>, // 合成画布（RGBA），处理局部帧 + dispose=Keep 的叠加
}

impl GifAnim {
    fn new(ctx: &egui::Context, bytes: &[u8]) -> Option<Self> {
        let bytes = bytes.to_vec();
        let mut iter = gif::DecodeOptions::new();
        iter.set_color_output(gif::ColorOutput::RGBA);
        let mut decoder = iter
            .read_info(BufReader::new(Cursor::new(bytes.clone())))
            .ok()?;
        let (w, h) = (decoder.width() as usize, decoder.height() as usize);
        let frame = decoder.read_next_frame().ok()??;
        let mut canvas = vec![0u8; w * h * 4];
        composite_frame(&mut canvas, w, h, &frame);
        apply_dispose(&mut canvas, w, h, &frame, None);
        let delay = frame_delay(&frame);
        let img = egui::ColorImage::from_rgba_unmultiplied([w, h], &canvas);
        let tex = ctx.load_texture("omenrgb-anim", img, egui::TextureOptions::NEAREST);
        Some(Self {
            bytes,
            iter: Some(decoder),
            tex,
            delay_ms: delay,
            next_t: 0.0,
            w,
            h,
            canvas,
        })
    }

    fn advance(&mut self, ctx: &egui::Context, now: f64) {
        if now < self.next_t {
            return;
        }
        let Some(decoder) = &mut self.iter else {
            return;
        };
        match decoder.read_next_frame() {
            Ok(Some(frame)) => {
                let saved = if frame.dispose == gif::DisposalMethod::Previous {
                    Some(save_region(&self.canvas, self.w, &frame))
                } else {
                    None
                };
                composite_frame(&mut self.canvas, self.w, self.h, &frame);
                let delay = frame_delay(&frame);
                let img = egui::ColorImage::from_rgba_unmultiplied(
                    [self.w, self.h],
                    &self.canvas,
                );
                self.tex.set(img, egui::TextureOptions::NEAREST);
                self.delay_ms = delay;
                self.next_t = now + delay;
                apply_dispose(&mut self.canvas, self.w, self.h, &frame, saved);
            }
            _ => self.restart(ctx, now),
        }
    }

    fn restart(&mut self, _ctx: &egui::Context, now: f64) {
        let mut opts = gif::DecodeOptions::new();
        opts.set_color_output(gif::ColorOutput::RGBA);
        let Ok(mut decoder) = opts.read_info(BufReader::new(Cursor::new(self.bytes.clone()))) else {
            return;
        };
        if let Ok(Some(frame)) = decoder.read_next_frame() {
            self.canvas.fill(0);
            composite_frame(&mut self.canvas, self.w, self.h, &frame);
            apply_dispose(&mut self.canvas, self.w, self.h, &frame, None);
            let delay = frame_delay(&frame);
            let img = egui::ColorImage::from_rgba_unmultiplied(
                [self.w, self.h],
                &self.canvas,
            );
            self.tex.set(img, egui::TextureOptions::NEAREST);
            self.delay_ms = delay;
            self.next_t = now + delay;
        }
        self.iter = Some(decoder);
    }
}

fn frame_delay(frame: &gif::Frame) -> f64 {
    // gif delay 单位 1/100 秒
    (frame.delay.max(2) as f64 / 100.0).max(0.02)
}

/// 将局部帧合成到画布：不透明像素覆盖，透明像素保留画布内容。
fn composite_frame(canvas: &mut [u8], w: usize, h: usize, f: &gif::Frame) {
    for y in 0..f.height as usize {
        let cy = f.top as usize + y;
        if cy >= h {
            continue;
        }
        for x in 0..f.width as usize {
            let cx = f.left as usize + x;
            if cx >= w {
                continue;
            }
            let fi = (y * f.width as usize + x) * 4;
            if f.buffer[fi + 3] == 0 {
                continue;
            }
            let ci = (cy * w + cx) * 4;
            canvas[ci..ci + 4].copy_from_slice(&f.buffer[fi..fi + 4]);
        }
    }
}

fn save_region(canvas: &[u8], w: usize, f: &gif::Frame) -> Vec<u8> {
    let mut saved = Vec::new();
    for y in 0..f.height as usize {
        let cy = f.top as usize + y;
        if cy * w + f.width as usize + f.left as usize > canvas.len() / 4 {
            continue;
        }
        let start = (cy * w + f.left as usize) * 4;
        saved.extend_from_slice(&canvas[start..start + f.width as usize * 4]);
    }
    saved
}

/// 应用帧的 disposal 方法（影响下一帧的画布状态）。
fn apply_dispose(
    canvas: &mut [u8],
    w: usize,
    _h: usize,
    f: &gif::Frame,
    saved: Option<Vec<u8>>,
) {
    match f.dispose {
        gif::DisposalMethod::Background => {
            // 将本帧区域清为透明背景
            for y in 0..f.height as usize {
                let cy = f.top as usize + y;
                let start = (cy * w + f.left as usize) * 4;
                let end = start + f.width as usize * 4;
                if end <= canvas.len() {
                    canvas[start..end].fill(0);
                }
            }
        }
        gif::DisposalMethod::Previous => {
            if let Some(s) = saved {
                let mut idx = 0;
                for y in 0..f.height as usize {
                    let cy = f.top as usize + y;
                    let start = (cy * w + f.left as usize) * 4;
                    let end = start + f.width as usize * 4;
                    if end <= canvas.len() {
                        canvas[start..end].copy_from_slice(&s[idx..idx + f.width as usize * 4]);
                    }
                    idx += f.width as usize * 4;
                }
            }
        }
        gif::DisposalMethod::Keep | gif::DisposalMethod::Any => {}
    }
}

/// 动画内部名 → OGH 真实 GIF 资源（pre_1..9.gif 为 Dragon 模块 Effect 1..9 的预览）：
/// 1=ColorCycle、2=Starlight、3=Breathing、4=Ghosting、5=Ripple、6=Wave、
/// 7=OMEN X、8=Raindrop、9=Audio。四分区动画中 Confetti/Sun/Swipe 无对应素材，
/// 暂用形态最接近的预览（彩纸≈雨滴、太阳≈涟漪、滑动≈波浪）。
fn animation_gif(name: &str) -> Option<&'static [u8]> {
    match name {
        "colorcycle" => Some(include_bytes!("../assets/previews/pre_1.gif")),
        "starlight" => Some(include_bytes!("../assets/previews/pre_2.gif")),
        "breathing" => Some(include_bytes!("../assets/previews/pre_3.gif")),
        "wave" => Some(include_bytes!("../assets/previews/pre_6.gif")),
        "raindrop" => Some(include_bytes!("../assets/previews/pre_8.gif")),
        "audiopulse" => Some(include_bytes!("../assets/previews/pre_9.gif")),
        "confetti" => Some(include_bytes!("../assets/previews/pre_8.gif")),
        "sun" => Some(include_bytes!("../assets/previews/pre_5.gif")),
        "swipe" => Some(include_bytes!("../assets/previews/pre_6.gif")),
        _ => None,
    }
}

impl Default for App {
fn default() -> Self {
        Self {
            client: Client::new(),
            page: Page::System,
            dojo_zones: Vec::new(),
            zones: std::array::from_fn(|_| "FFFFFF".into()),
            brightness: 100,
            selected: 4,
            hex: "FF0000".into(),
            animation: "静态".into(),
            anim: None,
            status: "就绪".into(),
            status_color: MUTED,
            initial_refresh: true,
            profiles: Vec::new(),
            profile_name: String::new(),
            pick_hue: 0.0,
            pick_bright: 50.0,
            custom_running: None,
            custom_base: "FF2C74".into(),
            custom_speed: 1.0,
            hide_requested: false,
            last_vid: None,
            system: SystemStats::default(),
            last_cpu_sample: None,
            last_net_sample: None,
            last_system_refresh: Instant::now() - Duration::from_secs(10),
        }
    }
}

impl App {
    fn load_keyboard_layout(&mut self) {
        // Dojo 逐键光区只用于区域归属。将其按行对应到从本机截图量出的自有键帽几何，
        // 因此灯色、点击命中和可视键帽使用同一套矩形。
        let zones_json = include_str!("../assets/dojo-zones.json");
        let cleaned: String = zones_json
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        if let Ok(zf) = serde_json::from_str::<DojoZonesFile>(&cleaned) {
            let mut target_rows = vec![Vec::<[f32; 4]>::new(); 6];
            for key in OMEN16_KEY_RECTS {
                let row = if key[1] >= 239.0 {
                    5
                } else {
                    ((key[1] - 29.0) / 44.0).round() as usize
                };
                target_rows[row].push(*key);
            }
            for row in &mut target_rows {
                row.sort_by(|a, b| a[0].total_cmp(&b[0]));
            }

            let mut source_rows = vec![Vec::<(usize, f32)>::new(); 6];
            for (area, zone) in zf.zones.into_iter().enumerate() {
                for part in zone.into_iter().filter(|r| r.len() >= 4) {
                    let row = if part[1] >= 268.0 {
                        5
                    } else {
                        ((part[1] - 111.0) / 33.0).round() as usize
                    };
                    source_rows[row].push((area, part[0]));
                }
            }

            let mut mapped = vec![Vec::<[f32; 4]>::new(); 4];
            for row in 0..6 {
                source_rows[row].sort_by(|a, b| a.1.total_cmp(&b.1));
                for ((area, _), key) in source_rows[row].iter().zip(&target_rows[row]) {
                    mapped[*area].push(*key);
                }
                // 原灯区数据未列出右上角键和右下角数字区 Enter；两者实际随右侧/小键盘变色。
                for key in target_rows[row].iter().skip(source_rows[row].len()) {
                    mapped[0].push(*key);
                }
            }
            // 实机校准：T/G/V/B/Space 随硬件 zone 1（左侧、用户测试时为蓝色）变色。
            // mapped 的索引是 OGH area，area 2 才对应硬件 zone 1（hw = 3 - area）。
            for (x, y) in [(277.0, 107.0), (284.0, 151.0), (262.0, 195.0), (308.0, 195.0), (216.0, 240.0)] {
                for area in 0..4 {
                    if let Some(pos) = mapped[area]
                        .iter()
                        .position(|key| key[0] == x && key[1] == y)
                    {
                        let key = mapped[area].remove(pos);
                        mapped[2].push(key);
                        break;
                    }
                }
            }
            self.dojo_zones = mapped;
        }
    }

    fn set_animation(&mut self, ctx: &egui::Context, name: &str) {
        self.animation = name.to_string();
        self.anim = animation_gif(name).and_then(|b| GifAnim::new(ctx, b));
    }

    /// 启动主机驱动自定义动画（守护进程 30fps 循环写静态色）。
    fn start_custom_anim(&mut self, name: &str) {
        let base = self.custom_base.clone();
        let speed = self.custom_speed;
        match self.client.call("anim_start", &[name, &base, &speed.to_string()]) {
            Ok(_) => {
                self.custom_running = Some(name.to_string());
                self.status = format!("已启动自定义动画: {}", custom_anim_label(name));
                self.status_color = OK;
            }
            Err(e) => {
                self.status = format!("启动失败: {e}");
                self.status_color = ERR;
            }
        }
    }

    fn stop_custom_anim(&mut self) {
        match self.client.call("anim_stop", &[]) {
            Ok(_) => {
                self.custom_running = None;
                self.status = "已停止自定义动画".into();
                self.status_color = OK;
            }
            Err(e) => {
                self.status = format!("停止失败: {e}");
                self.status_color = ERR;
            }
        }
    }

    /// 读取 Linux 系统状态。所有来源均为 /proc、/sys 或 nvidia-smi，只读且失败可降级。
    fn refresh_system(&mut self) {
        let now = Instant::now();
        let (total, idle) = cpu_totals().unwrap_or((0, 0));
        if let Some((last_total, last_idle)) = self.last_cpu_sample {
            let dt = total.saturating_sub(last_total);
            let di = idle.saturating_sub(last_idle);
            if dt > 0 {
                self.system.cpu_usage = ((dt.saturating_sub(di)) as f32 / dt as f32 * 100.0)
                    .clamp(0.0, 100.0);
            }
        }
        self.last_cpu_sample = Some((total, idle));

        if let Some((used, total)) = memory_usage() {
            self.system.mem_used = used;
            self.system.mem_total = total;
        }
        self.system.cpu_temp = hwmon_temp(&["k10temp", "coretemp", "zenpower"])
            .or_else(|| thermal_temp("acpitz"));
        let (gpu_usage, gpu_temp) = nvidia_stats();
        self.system.gpu_usage = gpu_usage;
        self.system.gpu_temp = gpu_temp.or_else(|| hwmon_temp(&["amdgpu"]));
        self.system.load = std::fs::read_to_string("/proc/loadavg")
            .ok()
            .and_then(|s| s.split_whitespace().next()?.parse().ok())
            .unwrap_or(0.0);
        self.system.process_count = std::fs::read_dir("/proc")
            .ok()
            .map(|entries| {
                entries
                    .flatten()
                    .filter(|entry| entry.file_name().to_string_lossy().chars().all(|c| c.is_ascii_digit()))
                    .count()
            })
            .unwrap_or(0);

        let (rx, tx) = network_totals();
        if let Some((last_at, last_rx, last_tx)) = self.last_net_sample {
            let seconds = now.duration_since(last_at).as_secs_f64();
            if seconds > 0.0 {
                self.system.rx_rate = rx.saturating_sub(last_rx) as f64 / seconds;
                self.system.tx_rate = tx.saturating_sub(last_tx) as f64 / seconds;
            }
        }
        self.last_net_sample = Some((now, rx, tx));
        self.system.disks = disk_usage();
        self.last_system_refresh = now;
    }

    fn refresh(&mut self) {
        match self.client.call("status", &[]) {
            Ok(v) => {
                if let Some(z) = v["zones"].as_array() {
                    for (i, item) in z.iter().enumerate().take(4) {
                        if let Some(s) = item.as_str() {
                            self.zones[i] = s.to_string();
                        }
                    }
                }
                self.brightness = v["brightness"].as_u64().unwrap_or(100) as u8;
                self.custom_running = v["custom_anim"].as_str().map(|s| s.to_string());
                self.status = format!("状态已刷新（KBAM={}）", v["kbam"].as_u64().unwrap_or(0));
                self.status_color = OK;
            }
            Err(e) => {
                self.status = format!("无法连接守护进程: {e}");
                self.status_color = ERR;
            }
        }
    }

    fn refresh_profiles(&mut self) {
        match self.client.call("profile_list", &[]) {
            Ok(v) => {
                self.profiles = v["profiles"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .map(|p| {
                                let colors = p["colors"]
                                    .as_array()
                                    .map(|z| {
                                        z.iter()
                                            .map(|x| x.as_str().unwrap_or("?").to_string())
                                            .collect::<Vec<_>>()
                                            .join(",")
                                    })
                                    .unwrap_or_default();
                                (
                                    p["name"].as_str().unwrap_or("?").to_string(),
                                    colors,
                                    p["brightness"].as_u64().unwrap_or(0) as u8,
                                    p["animation"].as_str().unwrap_or("static").to_string(),
                                )
                            })
                            .collect()
                    })
                    .unwrap_or_default();
            }
            Err(e) => {
                self.status = format!("读取方案失败: {e}");
                self.status_color = ERR;
            }
        }
    }

    fn apply(&mut self, colors: [String; 4]) {
        let r = if self.selected == 4 {
            self.client.call("set_all", &[&colors[0]])
        } else {
            let i = self.selected;
            self.client
                .call("set_zone", &[&i.to_string(), &colors[i]])
        };
        match r {
            Ok(_) => {
                self.custom_running = None; // 守护进程已自动停止自定义动画
                self.zones = colors;
                let msg = if self.selected == 4 {
                    format!("已应用 #{} 到全部区域", self.hex)
                } else {
                    format!("已应用 #{} 到{}", self.hex, ZONE_NAMES[self.selected])
                };
                self.status = msg;
                self.status_color = OK;
            }
            Err(e) => {
                self.status = format!("设置失败: {e}");
                self.status_color = ERR;
            }
        }
    }

    fn apply_selected(&mut self) {
        let mut colors = self.zones.clone();
        if self.selected == 4 {
            for c in colors.iter_mut() {
                *c = self.hex.clone();
            }
        } else {
            colors[self.selected] = self.hex.clone();
        }
        self.apply(colors);
    }

    fn draw_keyboard(&mut self, ui: &mut egui::Ui) {
        let avail = ui.available_size();
        // 底部预留约 52px 给分区选择按钮，避免键盘把按钮挤成细条
        let size = Vec2::new(avail.x.max(300.0), (avail.y - 52.0).max(160.0));
        let (rect, response) = ui.allocate_exact_size(size, egui::Sense::click());
        let painter = ui.painter_at(rect);

        // 参考本机 OGH 截图重绘的 16 英寸全尺寸键盘：六排、右侧导航区和数字小键盘。
        // 884×316 是 omengh/键盘灯-无色.png 中外框的实测尺寸，不使用 OGH 图片素材。
        const REF_W: f32 = 884.0;
        const REF_H: f32 = 316.0;
        let scale = (size.x / REF_W).min(size.y / REF_H);
        let body = Rect::from_center_size(
            rect.center(),
            Vec2::new(REF_W * scale, REF_H * scale),
        );
        let outer_radius = 17.0 * scale;
        painter.rect_filled(body, outer_radius, Color32::from_rgb(0x32, 0x32, 0x32));
        painter.rect_stroke(
            body,
            outer_radius,
            Stroke::new((2.0 * scale).max(1.0), Color32::from_rgb(0x5A, 0x5A, 0x5A)),
            StrokeKind::Inside,
        );
        let well = body.shrink(16.0 * scale);
        painter.rect_filled(well, 12.0 * scale, Color32::from_rgb(0x0E, 0x0E, 0x0E));
        painter.rect_stroke(
            well,
            12.0 * scale,
            Stroke::new(scale.max(1.0), Color32::from_rgb(0x19, 0x19, 0x19)),
            StrokeKind::Inside,
        );

        // 先画出截图中的全部 101 个键帽；其中两个没有可控灯区，保持中性灰。
        for key in OMEN16_KEY_RECTS {
            let krect = Rect::from_min_size(
                Pos2::new(body.min.x + key[0] * scale, body.min.y + key[1] * scale),
                Vec2::new(key[2] * scale, key[3] * scale),
            );
            painter.rect_filled(krect, 3.5 * scale, Color32::from_rgb(0x3E, 0x3E, 0x3E));
        }
        let mut hit_rects: Vec<(Rect, usize)> = Vec::new();
        // 光区数据顺序(0=右,1=中,2=左,3=核心)与硬件实际顺序
        // (0=核心 QWER/ASDF, 1=左, 2=中, 3=右)相反，这里做映射：area → 硬件 zone = 3 - area。
        for (area, rects) in self.dojo_zones.iter().enumerate() {
            let hw_zone = 3 - area;
            let visible = self.selected == 4 || self.selected == hw_zone;
            let zone_color = hex_to_color(&self.zones[hw_zone]);
            for r in rects {
                let krect = Rect::from_min_size(
                    Pos2::new(body.min.x + r[0] * scale, body.min.y + r[1] * scale),
                    Vec2::new(r[2] * scale, r[3] * scale),
                );
                let fill = if visible {
                    Color32::from_rgba_unmultiplied(
                        zone_color.r(),
                        zone_color.g(),
                        zone_color.b(),
                        132,
                    )
                } else {
                    // 未选中也显示淡淡的本区颜色，保证整体可见
                    Color32::from_rgba_unmultiplied(
                        zone_color.r(),
                        zone_color.g(),
                        zone_color.b(),
                        48,
                    )
                };
                painter.rect_filled(krect, 3.5 * scale, fill);
                if visible {
                    painter.rect_stroke(
                        krect,
                        3.5 * scale,
                        Stroke::new(scale.max(1.0), zone_color.gamma_multiply(0.75)),
                        StrokeKind::Inside,
                    );
                } else {
                    painter.rect_stroke(
                        krect,
                        3.5 * scale,
                        Stroke::new((0.5 * scale).max(0.5), zone_color.gamma_multiply(0.3)),
                        StrokeKind::Inside,
                    );
                }
                hit_rects.push((krect, hw_zone));
            }
        }
        // 点击键盘上的分区 → 选中对应硬件 zone
        if response.clicked() {
            if let Some(pos) = response.interact_pointer_pos() {
                for (krect, hw) in &hit_rects {
                    if krect.contains(pos) {
                        self.selected = *hw;
                        break;
                    }
                }
            }
        }

        // 动画预览：OGH 真实 GIF（右下角小窗）
        if let Some(anim) = &self.anim {
            let now = ui.input(|i| i.time);
            let ps = 240.0_f32.min(size.x * 0.30).max(140.0);
            let pr = Rect::from_min_size(
                Pos2::new(rect.right() - ps - 8.0, rect.bottom() - ps * 0.427 - 8.0),
                Vec2::new(ps, ps * 0.427),
            );
            painter.image(
                anim.tex.id(),
                pr,
                Rect::from_min_max(Pos2::new(0.0, 0.0), Pos2::new(1.0, 1.0)),
                Color32::WHITE,
            );
            let _ = now;
        }
    }
}

impl App {
    fn draw_system_dashboard(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.heading(RichText::new("系统核心").color(TEXT));
            ui.label(RichText::new("实时读取本机 Linux 状态").size(11.0).color(MUTED));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("↻ 刷新监控").clicked() {
                    self.refresh_system();
                }
            });
        });
        let stats = &self.system;
        ui.add_space(10.0);
        ui.columns(3, |columns| {
            gauge_card(
                &mut columns[0],
                "CPU",
                stats.cpu_usage,
                format!("{:.0}%", stats.cpu_usage),
                stats
                    .cpu_temp
                    .map(|temp| format!("{temp:.0} °C"))
                    .unwrap_or_else(|| "温度不可用".into()),
                ACCENT,
            );
            let gpu_usage = stats.gpu_usage.unwrap_or(0.0);
            gauge_card(
                &mut columns[1],
                "GPU",
                gpu_usage,
                stats
                    .gpu_usage
                    .map(|usage| format!("{usage:.0}%"))
                    .unwrap_or_else(|| "--".into()),
                stats
                    .gpu_temp
                    .map(|temp| format!("{temp:.0} °C"))
                    .unwrap_or_else(|| "温度不可用".into()),
                Color32::from_rgb(0x8A, 0x5C, 0xFF),
            );
            let mem_pct = if stats.mem_total > 0 {
                stats.mem_used as f32 / stats.mem_total as f32 * 100.0
            } else {
                0.0
            };
            gauge_card(
                &mut columns[2],
                "内存",
                mem_pct,
                format!("{mem_pct:.0}%"),
                format!("{} / {}", human_bytes(stats.mem_used), human_bytes(stats.mem_total)),
                Color32::from_rgb(0x2E, 0xB9, 0xD8),
            );
        });

        ui.add_space(12.0);
        ui.columns(3, |columns| {
            dashboard_section(&mut columns[0], "网络", Color32::from_rgb(0x31, 0xC4, 0xE8), |ui| {
                ui.horizontal(|ui| {
                    ui.vertical(|ui| {
                        ui.label(RichText::new("↓ 下载").size(12.0).color(TEXT));
                        ui.label(RichText::new(human_rate(stats.rx_rate)).size(19.0).strong().color(TEXT));
                    });
                    ui.add_space(12.0);
                    ui.vertical(|ui| {
                        ui.label(RichText::new("↑ 上传").size(12.0).color(TEXT));
                        ui.label(RichText::new(human_rate(stats.tx_rate)).size(19.0).strong().color(TEXT));
                    });
                });
            });
            dashboard_section(&mut columns[1], "存储空间", Color32::from_rgb(0xFF, 0xA5, 0x2D), |ui| {
                if stats.disks.is_empty() {
                    ui.label(RichText::new("未读取到磁盘").color(TEXT));
                }
                for disk in stats.disks.iter().take(2) {
                    let usage = if disk.total > 0 { disk.used as f32 / disk.total as f32 } else { 0.0 };
                    ui.label(RichText::new(&disk.mount).monospace().size(12.0).color(TEXT));
                    ui.add(
                        egui::ProgressBar::new(usage)
                            .desired_width(ui.available_width())
                            .text(format!("{} / {}", human_bytes(disk.used), human_bytes(disk.total))),
                    );
                }
            });
            dashboard_section(&mut columns[2], "系统状态", OK, |ui| {
                ui.label(RichText::new(format!("负载（1 分钟）  {:.2}", stats.load)).color(TEXT));
                ui.label(RichText::new(format!("运行进程          {}", stats.process_count)).color(TEXT));
                ui.label(RichText::new("数据每秒刷新一次").size(11.0).color(TEXT));
            });
        });
    }

    /// 请求隐藏主窗口：置标志 + 立即唤醒根视口执行隐藏，
    /// 避免等到根视口 500ms 轮询才生效造成点击延迟。
    fn request_hide(&mut self, ctx: &egui::Context) {
        self.hide_requested = true;
        ctx.request_repaint_of(egui::ViewportId::ROOT);
    }

    /// 主窗口 UI（作为子视口渲染；关闭=销毁=Wayland 真隐藏，显示=重建）
    pub fn update_main_ui(&mut self, ctx: &egui::Context) {
        // 点窗口关闭键（X）→ 隐藏到托盘。egui 对非根视口只置 close_requested，
        // 需要应用自己在下帧停止渲染它（复用"隐藏到托盘"按钮的路径）。
        if ctx.input(|i| i.viewport().close_requested()) {
            self.request_hide(ctx);
        }
        // 视口重建（隐藏→显示）后 Context 会变：重建纹理与字体
        if self.last_vid != Some(ctx.viewport_id()) {
            self.last_vid = Some(ctx.viewport_id());
            self.anim = None;
            setup_fonts(ctx);
        }
        if self.dojo_zones.is_empty() {
            self.load_keyboard_layout();
        }
        let mut style = (*ctx.style()).clone();
        style.visuals = egui::Visuals::dark();
        style.visuals.panel_fill = BG;
        style.visuals.window_fill = PANEL;
        style.visuals.faint_bg_color = PANEL2;
        style.visuals.extreme_bg_color = PANEL;
        style.visuals.widgets.noninteractive.bg_fill = PANEL2;
        style.visuals.widgets.noninteractive.fg_stroke.color = TEXT;
        style.visuals.widgets.inactive.bg_fill = PANEL2;
        style.visuals.widgets.inactive.fg_stroke.color = TEXT;
        style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(0x2A, 0x2B, 0x38);
        style.visuals.widgets.active.bg_fill = ACCENT;
        style.visuals.widgets.active.fg_stroke.color = Color32::BLACK;
        ctx.set_style(style);
        if self.animation != "静态" {
            ctx.request_repaint();
        }
        // 启动时自动读取一次守护进程状态（分区颜色/亮度/模式）
        if self.initial_refresh {
            self.initial_refresh = false;
            self.refresh();
            self.refresh_profiles();
        }
        if self.page == Page::System {
            if self.last_system_refresh.elapsed() >= Duration::from_secs(1) {
                self.refresh_system();
            }
            ctx.request_repaint_after(Duration::from_secs(1));
        }
        // 驱动 GIF 预览播放
        if let Some(anim) = &mut self.anim {
            let now = ctx.input(|i| i.time);
            anim.advance(ctx, now);
            ctx.request_repaint();
        }

        egui::TopBottomPanel::top("header").frame(egui::Frame::NONE.fill(BG).inner_margin(16.0)).show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new("OMEN RGB").size(22.0).strong().color(ACCENT));
                ui.label(RichText::new("HP OMEN 16 · 四分区键盘灯控").size(11.0).color(MUTED));
                ui.add_space(10.0);
                for (page, label) in [(Page::System, "系统核心"), (Page::Lighting, "灯光")] {
                    if ui.selectable_label(self.page == page, RichText::new(label).size(13.0)).clicked() {
                        self.page = page;
                    }
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button(RichText::new("▁ 隐藏到托盘").color(Color32::WHITE)).clicked() {
                        self.request_hide(ctx);
                    }
                    if ui.button(RichText::new("↻ 刷新").color(Color32::WHITE)).clicked() {
                        self.refresh();
                    }
                });
            });
        });

        egui::TopBottomPanel::bottom("status").frame(egui::Frame::NONE.fill(PANEL).inner_margin(10.0)).show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(&self.status).color(self.status_color));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(RichText::new("写入立即生效").color(OK).weak());
                });
            });
        });

        if self.page == Page::Lighting {
        egui::SidePanel::right("side")
            .resizable(true)
            .default_width(300.0)
            .min_width(270.0)
            .max_width(400.0)
            .frame(egui::Frame::NONE.fill(BG).inner_margin(14.0))
            .show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(6.0);
                section(ui, "颜色", |ui| {
                    for (name, colors) in PRESET_GROUPS {
                        ui.horizontal(|ui| {
                            ui.add_space(2.0);
                            ui.label(RichText::new(*name).size(11.0).color(MUTED));
                        });
                        ui.horizontal_wrapped(|ui| {
                            for p in colors.iter() {
                                let (rect, resp) =
                                    ui.allocate_exact_size(Vec2::splat(30.0), egui::Sense::click());
                                ui.painter().rect_filled(rect, 5.0, hex_to_color(p));
                                // 浅色（白/灰）在深色背景上需要描边才看得清
                                ui.painter().rect_stroke(
                                    rect,
                                    5.0,
                                    egui::Stroke::new(1.0, Color32::from_gray(70)),
                                    egui::StrokeKind::Inside,
                                );
                                let resp = resp.on_hover_text(format!("#{p}"));
                                if resp.clicked() {
                                    self.hex = (*p).to_string();
                                    self.apply_selected();
                                }
                            }
                        });
                        ui.add_space(4.0);
                    }
                    ui.add_space(8.0);
                    ui.horizontal(|ui| {
                        ui.label(RichText::new("#").color(MUTED));
                        let edit = ui.add(
                            egui::TextEdit::singleline(&mut self.hex)
                                .font(FontId::monospace(15.0))
                                .desired_width(96.0)
                                .char_limit(6),
                        );
                        let _ = edit;
                    });
                    ui.add_space(8.0);
                    if ui
                        .button(RichText::new("✓ 应用到所选分区").size(13.0).color(Color32::WHITE))
                        .clicked()
                    {
                        self.apply_selected();
                    }
                });

                ui.add_space(10.0);
                section(ui, "高级配色（双条）", |ui| {
                    egui::CollapsingHeader::new(
                        RichText::new("双条调色（OGH 风格）").size(12.5).color(MUTED),
                    )
                    .default_open(false)
                    .show(ui, |ui| {
                        ui.label(RichText::new("色相").size(12.0).color(MUTED));
                        let hue_resp = gradient_slider(ui, &mut self.pick_hue, 0.0, 360.0, |t| {
                            let [r, g, b] = hsl_to_rgb(t * 360.0, 1.0, 0.5);
                            Color32::from_rgb(r, g, b)
                        });
                        let _ = hue_resp;
                        ui.add_space(2.0);
                        ui.label(RichText::new("灰度/亮度").size(12.0).color(MUTED));
                        let br_resp = gradient_slider(ui, &mut self.pick_bright, 0.0, 100.0, |t| {
                            let v = (t * 255.0) as u8;
                            Color32::from_rgb(v, v, v)
                        });
                        if hue_resp.dragged()
                            || hue_resp.clicked()
                            || br_resp.dragged()
                            || br_resp.clicked()
                        {
                            let [r, g, b] =
                                hsl_to_rgb(self.pick_hue, 1.0, self.pick_bright / 100.0);
                            self.hex = format!("{r:02X}{g:02X}{b:02X}");
                        }
                        ui.add_space(4.0);
                        ui.horizontal(|ui| {
                            let [r, g, b] =
                                hsl_to_rgb(self.pick_hue, 1.0, self.pick_bright / 100.0);
                            let (rect, _) =
                                ui.allocate_exact_size(Vec2::new(26.0, 26.0), egui::Sense::hover());
                            ui.painter().rect_filled(rect, 6.0, Color32::from_rgb(r, g, b));
                            ui.label(
                                RichText::new(format!("#{r:02X}{g:02X}{b:02X}"))
                                    .font(FontId::monospace(13.0)),
                            );
                            ui.label(
                                RichText::new("结果已写入 # 输入框")
                                    .size(10.0)
                                    .color(MUTED),
                            );
                        });
                    });
                });

                ui.add_space(10.0);
                section(ui, "亮度", |ui| {
                    // 实测：0=灭、1=灭、50=低亮、100=满亮；2-49 未确认。
                    // 开档之间（50↔100）切换暂不稳定，先提供 关/开 两段式。
                    ui.horizontal(|ui| {
                        for (label, level) in [("关", 0u8), ("开", 100u8)] {
                            let selected = self.brightness == level;
                            let text = if selected {
                                RichText::new(label).size(13.0).strong().color(Color32::BLACK)
                            } else {
                                RichText::new(label).size(13.0)
                            };
                            if ui.selectable_label(selected, text).clicked() {
                                self.custom_running = None;
                                self.brightness = level;
                                match self.client.call("brightness", &[&level.to_string()]) {
                                    Ok(_) => {
                                        self.status = format!("亮度已设为 {label}（{level}%）");
                                        self.status_color = OK;
                                    }
                                    Err(e) => {
                                        self.status = format!("设置失败: {e}");
                                        self.status_color = ERR;
                                    }
                                }
                            }
                        }
                    });
                });

                ui.add_space(10.0);
                section(ui, "配置方案", |ui| {
                    ui.horizontal(|ui| {
                        let edit = ui.add(
                            egui::TextEdit::singleline(&mut self.profile_name)
                                .desired_width(120.0)
                                .hint_text("方案名"),
                        );
                        let _ = edit;
                        if ui
                            .button(RichText::new("💾 保存当前").size(12.5).color(Color32::WHITE))
                            .clicked()
                        {
                            let name = self.profile_name.trim().to_string();
                            if name.is_empty() {
                                self.status = "请先输入方案名".into();
                                self.status_color = ERR;
                            } else {
                                match self.client.call("profile_save", &[&name]) {
                                    Ok(v) => {
                                        self.status = format!(
                                            "已保存方案: {}",
                                            v["saved"].as_str().unwrap_or("")
                                        );
                                        self.status_color = OK;
                                        self.profile_name.clear();
                                        self.refresh_profiles();
                                    }
                                    Err(e) => {
                                        self.status = format!("保存失败: {e}");
                                        self.status_color = ERR;
                                    }
                                }
                            }
                        }
                    });
                    ui.add_space(4.0);
                    if self.profiles.is_empty() {
                        ui.label(RichText::new("暂无方案，保存一个开始").color(MUTED).size(12.0));
                    }
                    let profiles = self.profiles.clone();
                    for (name, colors, brightness, animation) in &profiles {
                        ui.horizontal(|ui| {
                            let anim_label = if animation == "static" {
                                "静态".to_string()
                            } else {
                                animation_display_name(animation).1.to_string()
                            };
                            ui.label(
                                RichText::new(format!(
                                    "{name} · {brightness}% · {anim_label}"
                                ))
                                .size(12.5),
                            );
                            if ui.button(RichText::new("应用").size(12.0)).clicked() {
                                match self.client.call("profile_load", &[name]) {
                                    Ok(v) => {
                                        self.status = format!(
                                            "已应用方案: {}",
                                            v["loaded"].as_str().unwrap_or("")
                                        );
                                        self.status_color = OK;
                                        self.refresh();
                                    }
                                    Err(e) => {
                                        self.status = format!("应用失败: {e}");
                                        self.status_color = ERR;
                                    }
                                }
                            }
                            if ui
                                .button(RichText::new("删除").size(12.0).color(ERR))
                                .clicked()
                            {
                                match self.client.call("profile_delete", &[name]) {
                                    Ok(v) => {
                                        self.status = format!(
                                            "已删除方案: {}",
                                            v["deleted"].as_str().unwrap_or("")
                                        );
                                        self.status_color = OK;
                                        self.refresh_profiles();
                                    }
                                    Err(e) => {
                                        self.status = format!("删除失败: {e}");
                                        self.status_color = ERR;
                                    }
                                }
                            }
                        });
                        ui.label(RichText::new(format!("#{colors}")).size(10.0).color(MUTED));
                    }
                });

                ui.add_space(10.0);
                section(ui, "动画", |ui| {
                    let (en, cn) = animation_display_name(&self.animation);
                    let sel_text = if self.animation == "静态" {
                        "静态".to_string()
                    } else {
                        format!("{cn} ({en})")
                    };
                    egui::ComboBox::from_id_salt("anim")
                        .selected_text(sel_text)
                        .show_ui(ui, |ui| {
                            for a in ANIMATIONS {
                                let (en, cn) = animation_display_name(a);
                                let label = if a == "静态" {
                                    "静态".to_string()
                                } else {
                                    format!("{cn} ({en})")
                                };
                                if ui.selectable_label(self.animation == a, label).clicked() {
                                    self.set_animation(ctx, a);
                                }
                            }
                        });
                    ui.label(RichText::new("预览为模拟效果，发送后以键盘实机为准").color(MUTED).size(10.0));
                    if self.animation != "静态"
                        && ui.button("发送动画").clicked()
                    {
                        self.custom_running = None;
                        match self.client.call("animate", &[&self.animation]) {
                            Ok(_) => {
                                self.status = format!("已发送动画: {}", self.animation);
                                self.status_color = OK;
                            }
                            Err(e) => {
                                self.status = format!("设置失败: {e}");
                                self.status_color = ERR;
                            }
                        }
                    }
                });

                ui.add_space(10.0);
                section(ui, "自定义动画（主机驱动）", |ui| {
                    ui.horizontal(|ui| {
                        ui.label(RichText::new("基础色 #").size(12.0).color(MUTED));
                        let edit = ui.add(
                            egui::TextEdit::singleline(&mut self.custom_base)
                                .font(FontId::monospace(15.0))
                                .desired_width(82.0)
                                .char_limit(6),
                        );
                        let _ = edit;
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if let Some(name) = &self.custom_running {
                                ui.label(
                                    RichText::new(format!("▶ {}", custom_anim_label(name)))
                                        .size(12.0)
                                        .color(OK),
                                );
                            } else {
                                ui.label(RichText::new("未运行").size(12.0).color(MUTED));
                            }
                        });
                    });
                    ui.add_space(4.0);
                    ui.horizontal(|ui| {
                        ui.label(RichText::new("速度").size(12.0).color(MUTED));
                        ui.add(
                            egui::Slider::new(&mut self.custom_speed, 0.2..=2.0)
                                .show_value(false),
                        );
                        ui.label(
                            RichText::new(format!("{:.1}x", self.custom_speed))
                                .size(11.0)
                                .color(MUTED),
                        );
                    });
                    ui.add_space(4.0);
                    ui.horizontal_wrapped(|ui| {
                        for a in CUSTOM_ANIMS {
                            let running = self.custom_running.as_deref() == Some(a.name);
                            let text = if running {
                                RichText::new(format!("▶ {}", a.label_cn))
                                    .size(12.0)
                                    .strong()
                                    .color(Color32::BLACK)
                            } else {
                                RichText::new(a.label_cn).size(12.0)
                            };
                            if ui.selectable_label(running, text).clicked() {
                                self.start_custom_anim(a.name);
                            }
                        }
                    });
                    ui.add_space(4.0);
                    if self.custom_running.is_some()
                        && ui
                            .button(RichText::new("⏹ 停止自定义动画").size(12.5).color(ERR))
                            .clicked()
                    {
                        self.stop_custom_anim();
                    }
                    ui.label(
                        RichText::new(
                            "由主机逐帧驱动（30fps），仅影响四个分区；选静态色/固件动画会自动停止",
                        )
                        .size(10.0)
                        .color(MUTED),
                    );
                });
            });
        });
        }

        egui::CentralPanel::default().frame(egui::Frame::NONE.fill(BG).inner_margin(12.0)).show(ctx, |ui| {
            if self.page == Page::System {
                self.draw_system_dashboard(ui);
                return;
            }
            ui.horizontal(|ui| {
                ui.label(RichText::new("点击分区选择颜色").color(MUTED).size(11.0));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let label = if self.selected == 4 {
                        "当前选择: 全部区域".to_string()
                    } else {
                        format!("当前选择: {}", ZONE_NAMES[self.selected])
                    };
                    ui.label(RichText::new(label).color(ACCENT).strong());
                });
            });
            ui.add_space(6.0);
            self.draw_keyboard(ui);
            ui.add_space(8.0);
            ui.horizontal_wrapped(|ui| {
                if zone_chip(ui, self.selected == 4, "全部区域", hex_to_color("#FFFFFF")).clicked() {
                    self.selected = 4;
                }
                for (i, name) in ZONE_NAMES.iter().enumerate() {
                    let color = hex_to_color(&self.zones[i]);
                    if zone_chip(ui, self.selected == i, name, color).clicked() {
                        self.selected = i;
                    }
                }
            });
        });
    }
}

fn cpu_totals() -> Option<(u64, u64)> {
    let line = std::fs::read_to_string("/proc/stat").ok()?;
    let values: Vec<u64> = line
        .lines()
        .next()?
        .split_whitespace()
        .skip(1)
        .filter_map(|v| v.parse().ok())
        .collect();
    let total = values.iter().sum();
    let idle = values.get(3).copied().unwrap_or(0) + values.get(4).copied().unwrap_or(0);
    Some((total, idle))
}

fn memory_usage() -> Option<(u64, u64)> {
    let text = std::fs::read_to_string("/proc/meminfo").ok()?;
    let value = |name: &str| {
        text.lines()
            .find_map(|line| line.strip_prefix(name))?
            .split_whitespace()
            .next()?
            .parse::<u64>()
            .ok()
            .map(|kb| kb * 1024)
    };
    let total = value("MemTotal:")?;
    let available = value("MemAvailable:")?;
    Some((total.saturating_sub(available), total))
}

fn hwmon_temp(names: &[&str]) -> Option<f32> {
    let entries = std::fs::read_dir("/sys/class/hwmon").ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        let name = std::fs::read_to_string(path.join("name")).ok()?;
        if !names.iter().any(|wanted| name.trim() == *wanted) {
            continue;
        }
        for index in 1..=8 {
            let input = path.join(format!("temp{index}_input"));
            if let Ok(raw) = std::fs::read_to_string(input) {
                if let Ok(milli) = raw.trim().parse::<f32>() {
                    return Some(milli / 1000.0);
                }
            }
        }
    }
    None
}

fn thermal_temp(kind: &str) -> Option<f32> {
    for entry in std::fs::read_dir("/sys/class/thermal").ok()?.flatten() {
        let path = entry.path();
        if std::fs::read_to_string(path.join("type")).ok()?.trim() != kind {
            continue;
        }
        if let Ok(raw) = std::fs::read_to_string(path.join("temp")) {
            if let Ok(milli) = raw.trim().parse::<f32>() {
                return Some(milli / 1000.0);
            }
        }
    }
    None
}

fn nvidia_stats() -> (Option<f32>, Option<f32>) {
    let output = std::process::Command::new("nvidia-smi")
        .args([
            "--query-gpu=utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ])
        .output();
    let Ok(output) = output else { return (None, None) };
    let text = String::from_utf8_lossy(&output.stdout);
    let Some(line) = text.lines().next() else { return (None, None) };
    let mut values = line.split(',').map(|v| v.trim().parse::<f32>().ok());
    (values.next().flatten(), values.next().flatten())
}

fn network_totals() -> (u64, u64) {
    let mut rx = 0;
    let mut tx = 0;
    if let Ok(text) = std::fs::read_to_string("/proc/net/dev") {
        for line in text.lines().skip(2) {
            let Some((name, values)) = line.split_once(':') else { continue };
            if name.trim() == "lo" {
                continue;
            }
            let values: Vec<u64> = values
                .split_whitespace()
                .filter_map(|v| v.parse().ok())
                .collect();
            rx += values.first().copied().unwrap_or(0);
            tx += values.get(8).copied().unwrap_or(0);
        }
    }
    (rx, tx)
}

fn disk_usage() -> Vec<DiskStat> {
    let Ok(output) = std::process::Command::new("df")
        .args(["-B1", "--output=source,size,avail,target"])
        .output()
    else {
        return Vec::new();
    };
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .skip(1)
        .filter_map(|line| {
            let parts: Vec<_> = line.split_whitespace().collect();
            if parts.len() < 4
                || !parts[0].starts_with("/dev/")
                || parts[3].starts_with("/run")
                || parts[3].starts_with("/tmp")
            {
                return None;
            }
            let total = parts[1].parse::<u64>().ok()?;
            let available = parts[2].parse::<u64>().ok()?;
            (total > 0).then(|| DiskStat {
                mount: parts[3].to_string(),
                used: total.saturating_sub(available),
                total,
            })
        })
        .take(4)
        .collect()
}

fn human_rate(value: f64) -> String {
    if value >= 1_000_000.0 {
        format!("{:.1} MB/s", value / 1_000_000.0)
    } else if value >= 1_000.0 {
        format!("{:.1} KB/s", value / 1_000.0)
    } else {
        format!("{value:.0} B/s")
    }
}

fn human_bytes(value: u64) -> String {
    if value >= 1 << 30 {
        format!("{:.1} GB", value as f64 / (1 << 30) as f64)
    } else {
        format!("{:.0} MB", value as f64 / (1 << 20) as f64)
    }
}

fn gauge_card(
    ui: &mut egui::Ui,
    title: &str,
    percent: f32,
    value: String,
    detail: String,
    accent: Color32,
) {
    egui::Frame::NONE
        .fill(Color32::from_rgb(0x27, 0x29, 0x35))
        .corner_radius(10.0)
        .stroke(Stroke::new(1.0, accent.gamma_multiply(0.70)))
        .inner_margin(12.0)
        .show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.set_min_height(142.0);
            ui.label(RichText::new(title).size(14.0).strong().color(TEXT));
            let (rect, _) = ui.allocate_exact_size(Vec2::new(154.0, 92.0), egui::Sense::hover());
            let center = Pos2::new(rect.center().x, rect.center().y - 2.0);
            let radius = 32.0;
            ui.painter().circle_stroke(center, radius, Stroke::new(3.0, Color32::from_gray(84)));
            let end = -std::f32::consts::FRAC_PI_2
                + std::f32::consts::TAU * (percent / 100.0).clamp(0.0, 1.0);
            let points = (0..=32)
                .map(|i| {
                    let t = i as f32 / 32.0;
                    let angle = -std::f32::consts::FRAC_PI_2
                        + (end + std::f32::consts::FRAC_PI_2) * t;
                    Pos2::new(center.x + radius * angle.cos(), center.y + radius * angle.sin())
                })
                .collect::<Vec<_>>();
            ui.painter().add(egui::Shape::line(points, Stroke::new(3.0, accent)));
            ui.painter().text(
                center,
                egui::Align2::CENTER_CENTER,
                value,
                FontId::proportional(20.0),
                TEXT,
            );
            ui.label(RichText::new(detail).size(12.0).color(TEXT));
        });
}

fn dashboard_section(
    ui: &mut egui::Ui,
    title: &str,
    accent: Color32,
    body: impl FnOnce(&mut egui::Ui),
) {
    egui::Frame::NONE
        .fill(Color32::from_rgb(0x27, 0x29, 0x35))
        .corner_radius(10.0)
        .stroke(Stroke::new(1.0, accent.gamma_multiply(0.65)))
        .inner_margin(12.0)
        .show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.set_min_height(116.0);
            ui.label(RichText::new(title).size(14.0).strong().color(accent));
            ui.add_space(8.0);
            body(ui);
        });
}

/// 分区选择按钮：较大尺寸，填充当前分区颜色，选中时高亮。
fn zone_chip(ui: &mut egui::Ui, selected: bool, name: &str, color: Color32) -> egui::Response {
    let text_color = if selected { Color32::BLACK } else { TEXT };
    let text = RichText::new(name).size(13.0).strong().color(text_color);
    let fill = if selected {
        color
    } else {
        // 未选中：面板色叠加 35% 分区色，仍能看出所属分区
        Color32::from_rgba_unmultiplied(
            (PANEL2.r() as u32 * 65 / 100 + color.r() as u32 * 35 / 100) as u8,
            (PANEL2.g() as u32 * 65 / 100 + color.g() as u32 * 35 / 100) as u8,
            (PANEL2.b() as u32 * 65 / 100 + color.b() as u32 * 35 / 100) as u8,
            255,
        )
    };
    let stroke = egui::Stroke::new(
        if selected { 2.0 } else { 1.0 },
        if selected { color } else { MUTED },
    );
    let btn = egui::Button::new(text)
        .min_size(Vec2::new(104.0, 38.0))
        .fill(fill)
        .stroke(stroke)
        .corner_radius(8.0);
    ui.add(btn)
}

fn section(ui: &mut egui::Ui, title: &str, body: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::NONE
        .fill(PANEL)
        .corner_radius(10.0)
        .inner_margin(12.0)
        .show(ui, |ui| {
            ui.label(RichText::new(title).size(12.0).strong().color(MUTED));
            ui.add_space(6.0);
            body(ui);
        });
}

fn setup_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let candidates = [
        "/home/xein/.local/share/fonts/LXGWWenKaiScreenNerdFont-Regular.ttf",
        "/home/xein/.local/share/fonts/LXGWWenKaiMonoGBScreenNerdFont-Regular.ttf",
        "/usr/share/fonts/wps-office/FZSSK.TTF",
        "/usr/share/fonts/WindowsFonts/msyh.ttc",
    ];
    for path in candidates {
        if let Ok(bytes) = std::fs::read(path) {
            fonts
                .font_data
                .insert("cjk".to_string(), std::sync::Arc::new(egui::FontData::from_owned(bytes)));
            fonts
                .families
                .entry(egui::FontFamily::Proportional)
                .or_default()
                .push("cjk".to_string());
            fonts
                .families
                .entry(egui::FontFamily::Monospace)
                .or_default()
                .push("cjk".to_string());
            break;
        }
    }
    ctx.set_fonts(fonts);
}

/// 窗口图标：使用自绘的 OMEN RGB 图标（黑底圆角 + 红橙渐变 O 环）。
fn window_icon() -> Option<Arc<egui::IconData>> {
    let bytes = include_bytes!("../../../icons/omenrgb-512.png");
    let img = image::load_from_memory(bytes).ok()?.to_rgba8();
    let (w, h) = img.dimensions();
    Some(Arc::new(egui::IconData {
        rgba: img.into_raw(),
        width: w,
        height: h,
    }))
}

/// 主窗口视口 ID（子视口：可独立销毁/重建，实现 Wayland 原生真隐藏）
fn main_vid() -> egui::ViewportId {
    egui::ViewportId::from_hash_of("omenrgb-main")
}

// KWin 脚本：把 1×1 根视口永久标记为 skipTaskbar/skipSwitcher/skipPager。
// Wayland 下没有 XDG 协议能从任务栏移除窗口，KDE 唯一正统做法就是 KWin 脚本。
// 这样隐藏主窗口（销毁 surface）后，任务栏不会残留根窗口的图标。
const KWIN_SKIP_JS: &str = r#"
function skipRoot(w) {
    if (w.resourceClass === "omenrgb" && w.frameGeometry.width < 20 && w.frameGeometry.height < 20) {
        w.skipTaskbar = true;
        w.skipSwitcher = true;
        w.skipPager = true;
    }
}
workspace.windowList().forEach(skipRoot);
workspace.windowAdded.connect(skipRoot);
"#;

/// 已加载的 KWin 脚本句柄（退出时卸载）
struct KwinSkip {
    plugin_name: String,
    _script_id: i32,
}

/// 向 KWin 注册根窗口跳过任务栏的脚本。仅 KDE/KWin 会话生效；其它环境静默失败。
fn install_kwin_skip() -> Option<KwinSkip> {
    // 完全没有显示环境时不尝试
    if std::env::var_os("WAYLAND_DISPLAY").is_none() && std::env::var_os("DISPLAY").is_none() {
        return None;
    }
    let plugin_name = format!("omenrgb-kwin-skip-{}", std::process::id());
    let script_path = std::env::temp_dir().join(format!("{plugin_name}.js"));
    if std::fs::write(&script_path, KWIN_SKIP_JS).is_err() {
        eprintln!("[omenrgb-gui] 无法写入 KWin 脚本文件，任务栏残留处理已跳过");
        return None;
    }
    let conn = match zbus::blocking::Connection::session() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[omenrgb-gui] 无法连接 session bus，任务栏残留处理已跳过: {e}");
            return None;
        }
    };
    // 同进程残留脚本（异常退出时）先卸载，避免堆积
    let _ = conn.call_method(
        Some("org.kde.KWin"),
        "/Scripting",
        Some("org.kde.kwin.Scripting"),
        "unloadScript",
        &plugin_name,
    );
    let path_str = script_path.to_str()?.to_string();
    let reply = match conn.call_method(
        Some("org.kde.KWin"),
        "/Scripting",
        Some("org.kde.kwin.Scripting"),
        "loadScript",
        &(path_str, plugin_name.clone()),
    ) {
        Ok(r) => r,
        Err(e) => {
            // 非 KDE 会话（GNOME 等）没有 org.kde.KWin，属正常
            eprintln!("[omenrgb-gui] KWin 脚本加载失败（非 KDE 时属正常）: {e}");
            return None;
        }
    };
    let script_id: i32 = match reply.body().deserialize() {
        Ok(id) => id,
        Err(e) => {
            eprintln!("[omenrgb-gui] KWin 脚本返回异常: {e}");
            return None;
        }
    };
    let run_path = format!("/Scripting/Script{script_id}");
    if let Err(e) = conn.call_method(
        Some("org.kde.KWin"),
        run_path.as_str(),
        Some("org.kde.kwin.Script"),
        "run",
        &(),
    ) {
        eprintln!("[omenrgb-gui] KWin 脚本运行失败: {e}");
        return None;
    }
    eprintln!("[omenrgb-gui] 已加载 KWin 脚本 → 根窗口不再出现在任务栏");
    Some(KwinSkip {
        plugin_name,
        _script_id: script_id,
    })
}

fn uninstall_kwin_skip(skip: &KwinSkip) {
    if let Ok(conn) = zbus::blocking::Connection::session() {
        let _ = conn.call_method(
            Some("org.kde.KWin"),
            "/Scripting",
            Some("org.kde.kwin.Scripting"),
            "unloadScript",
            &skip.plugin_name,
        );
    }
}

/// eframe 应用：根视口不可见（仅事件循环载体），主界面是子视口
struct GuiApp {
    state: Arc<Mutex<App>>,
    tray_rx: mpsc::Receiver<TrayMsg>,
    main_open: bool,
    main_alive: bool,
    hiding: bool,
    kwin_skip: Option<KwinSkip>,
}

impl GuiApp {
    fn main_viewport_builder() -> egui::ViewportBuilder {
        egui::ViewportBuilder::default()
            .with_inner_size([960.0, 640.0])
            .with_min_inner_size([820.0, 560.0])
            .with_title("OMEN RGB 键盘控制器")
            // 任务栏图标：app_id 匹配 omenrgb.desktop
            .with_app_id("omenrgb")
            .with_icon(window_icon().expect("内置图标缺失"))
    }
}

impl eframe::App for GuiApp {
    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        if let Some(skip) = &self.kwin_skip {
            uninstall_kwin_skip(skip);
        }
    }

    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // 第二个实例发来 SIGUSR1 → 显示主窗口（并从托盘恢复）
        if SHOW_REQUESTED.swap(false, Ordering::Relaxed) {
            self.main_open = true;
            ctx.send_viewport_cmd_to(main_vid(), egui::ViewportCommand::Focus);
        }
        // 托盘消息
        while let Ok(msg) = self.tray_rx.try_recv() {
            match msg {
                TrayMsg::Show => self.main_open = true,
                TrayMsg::Quit => ctx.send_viewport_cmd(egui::ViewportCommand::Close),
            }
        }
        // 主窗口里的"隐藏到托盘"按钮
        if self.state.lock().unwrap().hide_requested {
            self.state.lock().unwrap().hide_requested = false;
            self.hiding = true;
            self.main_open = false;
        }
        // 子视口生命周期：
        // - 显示 = 每帧调用 show_viewport_deferred 创建
        // - 用户点窗口关闭 = 视口被销毁（Wayland 真隐藏），检测到消失后置 main_open=false
        let alive = ctx.input(|i| i.raw.viewports.contains_key(&main_vid()));
        if self.main_alive && !alive && !self.hiding {
            self.main_open = false; // 用户关闭主窗口 → 隐藏到托盘
        }
        self.hiding = false;
        self.main_alive = alive;
        if self.main_open {
            let state = Arc::clone(&self.state);
            ctx.show_viewport_deferred(
                main_vid(),
                Self::main_viewport_builder(),
                move |ctx, _class| {
                    state.lock().unwrap().update_main_ui(ctx);
                },
            );
        }
        // 保持轮询托盘消息（窗口隐藏时应用仍在运行）
        ctx.request_repaint_after(std::time::Duration::from_millis(500));
    }
}

fn main() -> eframe::Result {
    // 单实例：已有实例时请求其显示窗口并退出
    let _instance_lock = match acquire_single_instance_lock() {
        Some(f) => f,
        None => std::process::exit(1),
    };
    unsafe {
        libc::signal(libc::SIGUSR1, handle_show_signal as libc::sighandler_t);
    }
    let kwin_skip = install_kwin_skip();
    let options = eframe::NativeOptions {
        // 根视口仅作事件循环载体：创建时即不可见（Wayland/X11 都支持初始隐藏）
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1.0, 1.0])
            .with_visible(false)
            .with_decorations(false)
            .with_app_id("omenrgb")
            .with_icon(window_icon().expect("内置图标缺失")),
        ..Default::default()
    };
    eframe::run_native(
        "omenrgb",
        options,
        Box::new(|cc| {
            setup_fonts(&cc.egui_ctx);
            // 系统托盘（KDE/SNI）：启动失败不致命，窗口仍可正常使用。
            // 持有 egui Context，托盘"显示主界面"可直接唤醒事件循环（无轮询延迟）。
            let (tray_tx, tray_rx) = mpsc::channel::<TrayMsg>();
            let tray = TrayApp {
                tx: tray_tx,
                ctx: cc.egui_ctx.clone(),
            };
            if let Err(e) = async_io::block_on(tray.spawn()) {
                eprintln!("[omenrgb-gui] 托盘启动失败: {e}");
            }
            let app = GuiApp {
                state: Arc::new(Mutex::new(App::default())),
                tray_rx,
                main_open: true, // 启动即显示主窗口
                main_alive: false,
                hiding: false,
                kwin_skip,
            };
            Ok(Box::new(app))
        }),
    )
}
