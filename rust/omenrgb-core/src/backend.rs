//! 灯效操作封装（守护进程使用，需要 root）。

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

use crate::payload;
use crate::wmi;
use crate::{
    animation_mode_byte, kbam, CMDT_GET_BRIGHTNESS, CMDT_GET_COLOR, CMDT_LIGHTBAR_MAILBOX,
    CMDT_SET_BRIGHTNESS, CMDT_SET_COLOR, CMD_BACKLIGHT,
};

#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub backend: &'static str,
    pub zones: [String; 4],
    pub brightness: i64,
    pub mode: &'static str,
    pub speed: u8,
    pub gradient: String,
    pub kbam: Option<u8>,
    pub kbam_label: Option<String>,
}

/// 持久化状态：守护进程每次改动后写入，启动时恢复。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SavedState {
    pub colors: [String; 4],
    pub brightness: u8,
    /// "static" 或动画内部名（colorcycle/starlight/...）
    pub animation: String,
}

pub struct Backend {
    last_colors: Option<[String; 4]>,
    last_brightness: u8,
    last_animation: String,
    state_path: PathBuf,
}

impl Default for Backend {
    fn default() -> Self {
        Self {
            last_colors: None,
            last_brightness: 100,
            last_animation: "static".to_string(),
            state_path: std::env::var("OMENRGB_STATE_PATH")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/var/lib/omenrgb/state.json")),
        }
    }
}

impl Backend {
    pub fn new() -> Self {
        Self::default()
    }

    /// 从磁盘读取上次保存的状态（不应用，只填充内存字段）。
    fn load_state(&mut self) -> Result<(), String> {
        let text = std::fs::read_to_string(&self.state_path)
            .map_err(|e| format!("读取状态 {} 失败: {e}", self.state_path.display()))?;
        let state: SavedState = serde_json::from_str(&text)
            .map_err(|e| format!("解析状态 {} 失败: {e}", self.state_path.display()))?;
        self.last_colors = Some(state.colors);
        self.last_brightness = state.brightness.clamp(0, 100);
        self.last_animation = if animation_mode_byte(&state.animation).is_some() {
            state.animation
        } else {
            "static".to_string()
        };
        Ok(())
    }

    /// 把当前状态写入磁盘（失败不致命，仅记录）。
    fn save_state(&self) {
        let Some(colors) = &self.last_colors else { return };
        let state = SavedState {
            colors: colors.clone(),
            brightness: self.last_brightness,
            animation: self.last_animation.clone(),
        };
        let result = (|| -> Result<(), String> {
            if let Some(parent) = self.state_path.parent() {
                std::fs::create_dir_all(parent)
                    .map_err(|e| format!("创建 {} 失败: {e}", parent.display()))?;
            }
            let tmp = self.state_path.with_extension("json.tmp");
            std::fs::write(&tmp, serde_json::to_string_pretty(&state).unwrap())
                .map_err(|e| format!("写入 {} 失败: {e}", tmp.display()))?;
            std::fs::rename(&tmp, &self.state_path)
                .map_err(|e| format!("保存 {} 失败: {e}", self.state_path.display()))?;
            Ok(())
        })();
        if let Err(e) = result {
            eprintln!("[omenrgbd] 保存状态失败: {e}");
        }
    }

    /// 启动时恢复上次状态：读盘并重放颜色/亮度/动画。
    pub fn restore(&mut self) -> Result<(), String> {
        if let Err(e) = self.load_state() {
            // 没有存档或存档损坏：保持默认，不视为错误
            eprintln!("[omenrgbd] 无可用状态，跳过恢复: {e}");
            return Ok(());
        }
        if self.last_animation != "static" {
            let name = self.last_animation.clone();
            self.animate(&name)?;
        } else if let Some(colors) = self.last_colors.clone() {
            self.set_colors(&colors, self.last_brightness)?;
        }
        eprintln!("[omenrgbd] 已恢复上次状态");
        Ok(())
    }

    fn read_zones(&self) -> Result<[String; 4], String> {
        let table = wmi::wmaa(CMD_BACKLIGHT, CMDT_GET_COLOR, &[], 128)?;
        let zones = payload::zones_from_table(&table);
        let mut out = std::array::from_fn(|_| String::new());
        for (i, z) in zones.iter().enumerate() {
            out[i] = z.clone();
        }
        Ok(out)
    }

    fn read_brightness(&self) -> Result<i64, String> {
        let b = wmi::wmaa(CMD_BACKLIGHT, CMDT_GET_BRIGHTNESS, &[], 4)?;
        match b.first() {
            Some(0xE4) => Ok(100),
            Some(0x64) => Ok(0),
            Some(v) => Ok(*v as i64),
            None => Ok(0),
        }
    }

    /// 写 EC 背光总开关（LBRT）：0xE4=开、0x64=关。
    /// 注意：LBRT 只有开/关两态，中间亮度由 LightBarCmdByte[3] 实时控制。
    fn write_lbrt(value: u8) -> Result<(), String> {
        wmi::wmaa(CMD_BACKLIGHT, CMDT_SET_BRIGHTNESS, &[value], 1).map(|_| ())
    }

    pub fn get_state(&mut self) -> Result<Status, String> {
        let zones = self.read_zones()?;
        // EC 的 LBRT 只表达“开/关”，读回永远是 0 或 100；
        // 实时亮度以最后写入的等级为准，否则 GUI 滑块每次都会被拉回 100%。
        let lbrt = self.read_brightness()?;
        let brightness = if lbrt == 0 { 0 } else { self.last_brightness as i64 };
        let (kbam, kbam_label) = match kbam::read_kbam() {
            Ok(v) => (Some(v), Some(format!("模式 {v}"))),
            Err(_) => (None, None),
        };
        self.last_colors = Some(zones.clone());
        self.last_brightness = brightness.clamp(0, 100) as u8;
        Ok(Status {
            backend: "omenrgbd",
            zones,
            brightness,
            mode: "static",
            speed: 1,
            gradient: String::new(),
            kbam,
            kbam_label,
        })
    }

    pub fn set_colors(&mut self, colors: &[String; 4], brightness: u8) -> Result<(), String> {
        let p = payload::static_payload(colors, brightness)?;
        wmi::wmaa(CMD_BACKLIGHT, CMDT_LIGHTBAR_MAILBOX, &p, 8)?;
        let legacy = payload::legacy_color_table(colors)?;
        let _ = wmi::wmaa(CMD_BACKLIGHT, CMDT_SET_COLOR, &legacy, 128);
        self.last_colors = Some(colors.clone());
        self.last_brightness = brightness;
        self.last_animation = "static".to_string();
        self.save_state();
        Ok(())
    }

    pub fn set_all(&mut self, rgb: &str, brightness: Option<u8>) -> Result<(), String> {
        let colors = [rgb.to_string(), rgb.to_string(), rgb.to_string(), rgb.to_string()];
        self.set_colors(&colors, brightness.unwrap_or(self.last_brightness))
    }

    pub fn set_zone(&mut self, index: usize, rgb: &str, brightness: Option<u8>) -> Result<(), String> {
        if index >= 4 {
            return Err("区域索引必须是 0-3".into());
        }
        let mut colors = match &self.last_colors {
            Some(c) => c.clone(),
            None => self.read_zones()?,
        };
        colors[index] = rgb.to_string();
        self.set_colors(&colors, brightness.unwrap_or(self.last_brightness))
    }

    pub fn set_brightness(&mut self, level: u8) -> Result<(), String> {
        if level > 100 {
            return Err("亮度必须是 0-100".into());
        }
        // 实测：EC 只有在 LBRT 刚被写过（0x64=关 / 0xE4=开）后，才会接受
        // 随后的邮箱亮度字节；否则 50↔100 这类同开状态间的切换会被忽略。
        // 因此每次亮度变化都先写一次 LBRT 触发提交。
        Self::write_lbrt(if level == 0 { 0x64 } else { 0xE4 })?;
        let colors = match &self.last_colors {
            Some(c) => c.clone(),
            None => self.read_zones()?,
        };
        self.set_colors(&colors, level)
    }

    pub fn animate(&mut self, name: &str) -> Result<(), String> {
        let mode = animation_mode_byte(name).ok_or_else(|| format!("未知动画: {name}"))?;
        let colors = match &self.last_colors {
            Some(c) => c.clone(),
            None => self.read_zones()?,
        };
        let p = payload::lightbar_payload(&colors, mode, self.last_brightness, 1)?;
        wmi::wmaa(CMD_BACKLIGHT, CMDT_LIGHTBAR_MAILBOX, &p, 8)?;
        self.last_colors = Some(colors);
        self.last_animation = name.to_string();
        self.save_state();
        Ok(())
    }

    pub fn static_colors(&mut self, brightness: Option<u8>) -> Result<(), String> {
        let colors = match &self.last_colors {
            Some(c) => c.clone(),
            None => self.read_zones()?,
        };
        self.set_colors(&colors, brightness.unwrap_or(self.last_brightness))
    }

}
