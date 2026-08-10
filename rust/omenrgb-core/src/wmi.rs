//! 通过 acpi_call 调用 \\_SB.WMID.WMAA（需要 root）。

use std::fs;
use std::io::{Read, Write};

const CALL_PATH: &str = "/proc/acpi/call";
const WMAA: &str = r"\_SB.WMID.WMAA";
const SECU: u32 = 0x5543_4553;
const PASS: u32 = 0x5353_4150;

fn mid_for_outsize(outsize: u32) -> u32 {
    if outsize > 128 {
        4
    } else if outsize > 4 {
        3
    } else if outsize > 0 {
        2
    } else {
        1
    }
}

/// 执行一次 WMAA 调用，返回响应数据（PASS 头之后的字节）。
pub fn wmaa(command: u32, cmdtype: u32, payload: &[u8], outsize: u32) -> Result<Vec<u8>, String> {
    let mut buf = Vec::with_capacity(16 + payload.len());
    buf.extend_from_slice(&SECU.to_le_bytes());
    buf.extend_from_slice(&command.to_le_bytes());
    buf.extend_from_slice(&cmdtype.to_le_bytes());
    buf.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    buf.extend_from_slice(payload);

    let mid = mid_for_outsize(outsize);
    let line = format!("{WMAA} 0 {mid} b{}", hex::encode(&buf));
    eprintln!("[wmi] cmd={command:#x} type={cmdtype:#x} -> {line}");

    // 注意：acpi_call 每次 write() 都按一条命令处理，必须把命令和换行
    // 放在同一次写入里（与 Python 实现一致）。
    let mut f = fs::OpenOptions::new()
        .write(true)
        .open(CALL_PATH)
        .map_err(|e| format!("打开 {CALL_PATH} 失败: {e}（需要 root）"))?;
    f.write_all(format!("{line}\n").as_bytes())
        .map_err(|e| format!("写入 acpi_call 失败: {e}"))?;
    drop(f);
    let mut f = fs::File::open(CALL_PATH)
        .map_err(|e| format!("打开 {CALL_PATH} 失败: {e}（需要 root）"))?;
    // 注意：acpi_call 的 read 回调在用户缓冲小于结果时直接返回 0（视为 EOF）。
    // Rust 的 read_to_string 首读只有 32 字节缓冲，会读到空串；必须用大缓冲。
    let mut buf = vec![0u8; 4096];
    let n = f.read(&mut buf).map_err(|e| format!("读取 acpi_call 失败: {e}"))?;
    let result = String::from_utf8_lossy(&buf[..n]).to_string();
    eprintln!("[wmi] <= {:?}", result);
    parse_result(&result)
}

fn parse_result(text: &str) -> Result<Vec<u8>, String> {
    let mut raw = Vec::new();
    let mut rest = text;
    while let Some(pos) = rest.find("0x") {
        let hex_part = &rest[pos + 2..];
        let end = hex_part
            .find(|c: char| !c.is_ascii_hexdigit())
            .unwrap_or(hex_part.len());
        let byte = u8::from_str_radix(&hex_part[..end.min(2)], 16)
            .map_err(|_| format!("解析 acpi_call 输出失败: {text}"))?;
        raw.push(byte);
        rest = &hex_part[end..];
    }
    if raw.len() < 8 {
        return Err(format!("WMAA 返回过短: {text}"));
    }
    let sig = u32::from_le_bytes(raw[0..4].try_into().unwrap());
    let retc = u32::from_le_bytes(raw[4..8].try_into().unwrap());
    if sig != PASS {
        return Err(format!("WMAA 返回签名异常 0x{sig:08X} (RETC=0x{retc:X}): {text}"));
    }
    if retc != 0 {
        return Err(format!("WMAA 返回错误码 0x{retc:X}"));
    }
    Ok(raw[8..].to_vec())
}

/// 极简 hex 编码（避免额外依赖）。
pub mod hex {
    pub fn encode(data: &[u8]) -> String {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut out = String::with_capacity(data.len() * 2);
        for b in data {
            out.push(HEX[(b >> 4) as usize] as char);
            out.push(HEX[(b & 0xF) as usize] as char);
        }
        out
    }
}
