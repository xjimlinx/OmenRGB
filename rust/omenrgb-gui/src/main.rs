//! OMEN RGB 键盘控制器 — egui 深色游戏风 GUI（经守护进程读写）。

use eframe::egui::{self, Color32, FontId, Pos2, Rect, RichText, Stroke, StrokeKind, TextureHandle, Vec2};
use omenrgb_core::client::Client;
use omenrgb_core::animation_display_name;
use omenrgb_core::ZONE_NAMES;
use std::io::{BufReader, Cursor};
use std::sync::Arc;

// OMEN 风格深色主题：暖黑背景 + 图标同款红粉主色（#FF2C74 → #FF6A3D 渐变系）
const BG: Color32 = Color32::from_rgb(0x10, 0x11, 0x16);
const PANEL: Color32 = Color32::from_rgb(0x19, 0x1A, 0x22);
const PANEL2: Color32 = Color32::from_rgb(0x22, 0x23, 0x2E);
const TEXT: Color32 = Color32::from_rgb(0xF0, 0xF1, 0xF6);
const MUTED: Color32 = Color32::from_rgb(0x9C, 0x9D, 0xA8);
const ACCENT: Color32 = Color32::from_rgb(0xFF, 0x2C, 0x74);
const ACCENT_ORANGE: Color32 = Color32::from_rgb(0xFF, 0x6A, 0x3D);
const OK: Color32 = Color32::from_rgb(0x4C, 0xC3, 0x8A);
const ERR: Color32 = Color32::from_rgb(0xFF, 0x4D, 0x4F);

const PRESETS: [&str; 16] = [
    "FF3B30", "FF9500", "FFCC00", "34C759",
    "00C7BE", "007AFF", "5856D6", "AF52DE",
    "FF2D55", "FF6482", "FFD60A", "30D158",
    "64D2FF", "5E5CE6", "BF5AF2", "FFFFFF",
];

const ANIMATIONS: [&str; 10] = [
    "静态", "colorcycle", "starlight", "breathing", "wave",
    "raindrop", "audiopulse", "confetti", "sun", "swipe",
];

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

struct App {
    client: Client,
    keyboard: Option<TextureHandle>,
    keyboard_size: [usize; 2],
    // DojoUS.json 解析出的四个分区的逐键光区（OGH FourZone 模块原始数据）
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
            keyboard: None,
            keyboard_size: [0, 0],
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
        }
    }
}

impl App {
    fn load_keyboard(&mut self, ctx: &egui::Context) {
        // OGH 灯光页 Dojo 机型的真实键盘底图（keyboard-blank-gamora.png，无键帽字体）
        let bytes = include_bytes!("../assets/keyboard-gamora.png");
        let img = image::load_from_memory(bytes).unwrap().to_rgba8();
        let (w, h) = img.dimensions();
        let color_image = egui::ColorImage::from_rgba_unmultiplied(
            [w as usize, h as usize],
            img.as_raw(),
        );
        self.keyboard = Some(ctx.load_texture(
            "omenrgb-keyboard",
            color_image,
            egui::TextureOptions::LINEAR,
        ));
        self.keyboard_size = [w as usize, h as usize];

        // 解析 OGH FourZone 的 DojoUS.json：4 个分区的逐键光区（原始坐标 260..872 × 111..297）
        let zones_json = include_str!("../assets/dojo-zones.json");
        let cleaned: String = zones_json
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        if let Ok(zf) = serde_json::from_str::<DojoZonesFile>(&cleaned) {
            self.dojo_zones = zf
                .zones
                .into_iter()
                .map(|zone| {
                    zone.into_iter()
                        .filter_map(|r| {
                            if r.len() < 4 {
                                return None;
                            }
                            Some([r[0], r[1], r[2], r[3]])
                        })
                        .collect::<Vec<_>>()
                })
                .collect();
        }
    }

    fn set_animation(&mut self, ctx: &egui::Context, name: &str) {
        self.animation = name.to_string();
        self.anim = animation_gif(name).and_then(|b| GifAnim::new(ctx, b));
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
                self.status = format!("状态已刷新（KBAM={}）", v["kbam"].as_u64().unwrap_or(0));
                self.status_color = OK;
            }
            Err(e) => {
                self.status = format!("无法连接守护进程: {e}");
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

        // 键盘图片（OGH Dojo 底图 keyboard-blank-gamora.png，保持宽高比）
        let (kw, kh) = (self.keyboard_size[0] as f32, self.keyboard_size[1] as f32);
        let scale = if kw > 0.0 && kh > 0.0 {
            (size.x / kw).min(size.y / kh)
        } else {
            1.0
        };
        let body = Rect::from_center_size(
            rect.center(),
            Vec2::new(kw * scale, kh * scale),
        );
        if let Some(tex) = &self.keyboard {
            painter.image(
                tex.id(),
                body,
                Rect::from_min_max(Pos2::new(0.0, 0.0), Pos2::new(1.0, 1.0)),
                Color32::WHITE,
            );
        }

        // DojoUS 四分区逐键光区：OGH 原始坐标(260..872, 111..297)
        // → 底图 keyboard-blank-gamora.png(684×272) 的内边框键盘面板
        //   (8..664 × 20..240，y 242 以下是掌托)，等比缩放并垂直居中。
        let jx0 = 260.0_f32;
        let jy0 = 111.0_f32;
        let jw = 872.0_f32 - jx0; // 612
        let jh = 297.0_f32 - jy0; // 186
        let ix0 = 8.0_f32;
        let iy0 = 20.0_f32;
        let iw = 656.0_f32;
        let ih = 220.0_f32;
        // 稍缩小一点并在面板内右偏（相对外框），视觉上更贴近 OGH 的布局。
        let s = (iw / jw).min(ih / jh) * 0.96;
        let kw = jw * s;
        let center_x = (ix0 + iw / 2.0) + 8.0;
        let left_x = center_x - kw / 2.0;
        let ox = body.min.x + (left_x - jx0 * s) * scale;
        let oy = body.min.y + (iy0 + (ih - jh * s) / 2.0 - jy0 * s) * scale;
        let mut hit_rects: Vec<(Rect, usize)> = Vec::new();
        // 注意：OGH DojoUS 的 JSON 分区顺序(0=右,1=中,2=左,3=核心)与硬件实际顺序
        // (0=核心 QWER/ASDF, 1=左, 2=中, 3=右)相反，这里做映射：area → 硬件 zone = 3 - area。
        for (area, rects) in self.dojo_zones.iter().enumerate() {
            let hw_zone = 3 - area;
            let visible = self.selected == 4 || self.selected == hw_zone;
            let zone_color = hex_to_color(&self.zones[hw_zone]);
            for r in rects {
                let kx = ox + r[0] * s * scale;
                let ky = oy + r[1] * s * scale;
                let krect = Rect::from_min_size(
                    Pos2::new(kx, ky),
                    Vec2::new(r[2] * s * scale, r[3] * s * scale),
                );
                let fill = if visible {
                    Color32::from_rgba_unmultiplied(
                        zone_color.r(),
                        zone_color.g(),
                        zone_color.b(),
                        110,
                    )
                } else {
                    // 未选中也显示淡淡的本区颜色，保证整体可见
                    Color32::from_rgba_unmultiplied(
                        zone_color.r(),
                        zone_color.g(),
                        zone_color.b(),
                        42,
                    )
                };
                painter.rect_filled(krect, 2.0, fill);
                if visible {
                    painter.rect_stroke(
                        krect,
                        2.0,
                        Stroke::new(1.0_f32, zone_color.gamma_multiply(0.75)),
                        StrokeKind::Inside,
                    );
                } else {
                    painter.rect_stroke(
                        krect,
                        2.0,
                        Stroke::new(0.5_f32, zone_color.gamma_multiply(0.3)),
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

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if self.keyboard.is_none() {
            self.load_keyboard(ctx);
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
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button(RichText::new("刷新").color(Color32::WHITE)).clicked() {
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

        egui::SidePanel::right("side").exact_width(300.0).frame(egui::Frame::NONE.fill(BG).inner_margin(14.0)).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(6.0);
                section(ui, "颜色", |ui| {
                    ui.horizontal_wrapped(|ui| {
                        for p in PRESETS {
                            let (rect, resp) = ui.allocate_exact_size(Vec2::splat(34.0), egui::Sense::click());
                            ui.painter().rect_filled(rect, 6.0, hex_to_color(p));
                            if resp.clicked() {
                                self.hex = p.to_string();
                                self.apply_selected();
                            }
                        }
                    });
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
                    if ui.button(RichText::new("应用到所选分区").size(13.0).color(Color32::WHITE)).clicked() {
                        self.apply_selected();
                    }
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
            });
        });

        egui::CentralPanel::default().frame(egui::Frame::NONE.fill(BG).inner_margin(12.0)).show(ctx, |ui| {
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

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([960.0, 640.0])
            .with_min_inner_size([820.0, 560.0])
            .with_title("OMEN RGB 键盘控制器")
            // Wayland: KDE 用 app_id 匹配 .desktop 文件名来决定任务栏/启动器图标，
            // 必须与 omenrgb.desktop 的文件名一致，窗口自绘图标只影响标题栏。
            .with_app_id("omenrgb")
            .with_icon(window_icon().expect("内置图标缺失")),
        ..Default::default()
    };
    eframe::run_native(
        "omenrgb",
        options,
        Box::new(|cc| {
            setup_fonts(&cc.egui_ctx);
            Ok(Box::new(App::default()))
        }),
    )
}
