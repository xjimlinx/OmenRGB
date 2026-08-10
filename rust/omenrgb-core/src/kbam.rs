//! 读取/写入键盘动画模式寄存器 KBAM（MMIO 0xFE70_0364，需要 root）。

use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom, Write};

const MMIO_BASE: u64 = 0xFE70_0000;
const REG_KBAM: u64 = 0x364;

pub fn read_kbam() -> Result<u8, String> {
    let mut f = OpenOptions::new()
        .read(true)
        .open("/dev/mem")
        .map_err(|e| format!("打开 /dev/mem 失败: {e}（需要 root）"))?;
    f.seek(SeekFrom::Start(MMIO_BASE + REG_KBAM))
        .map_err(|e| e.to_string())?;
    let mut b = [0u8; 1];
    f.read_exact(&mut b).map_err(|e| e.to_string())?;
    Ok(b[0])
}

pub fn write_kbam(value: u8) -> Result<(), String> {
    let mut f = OpenOptions::new()
        .write(true)
        .open("/dev/mem")
        .map_err(|e| format!("打开 /dev/mem 失败: {e}（需要 root）"))?;
    f.seek(SeekFrom::Start(MMIO_BASE + REG_KBAM))
        .map_err(|e| e.to_string())?;
    f.write_all(&[value]).map_err(|e| e.to_string())
}
