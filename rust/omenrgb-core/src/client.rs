//! omenrgbd 的 Unix socket 客户端（普通用户使用）。

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;

use serde_json::Value;

pub const DEFAULT_SOCK_PATH: &str = "/run/omenrgb/control.sock";

pub struct Client {
    path: String,
}

impl Client {
    pub fn new() -> Self {
        let path = std::env::var("OMENRGB_SOCK_PATH")
            .unwrap_or_else(|_| DEFAULT_SOCK_PATH.into());
        Self { path }
    }

    pub fn with_path(path: impl Into<String>) -> Self {
        Self { path: path.into() }
    }

    pub fn call(&self, cmd: &str, args: &[&str]) -> Result<Value, String> {
        let mut stream = UnixStream::connect(&self.path)
            .map_err(|e| format!("无法连接守护进程 {0}: {1}（请先安装服务）", self.path, e))?;
        let req = serde_json::json!({"cmd": cmd, "args": args});
        writeln!(stream, "{req}")
            .map_err(|e| format!("发送请求失败: {e}"))?;
        let mut reader = BufReader::new(stream);
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|e| format!("读取响应失败: {e}"))?;
        let resp: Value = serde_json::from_str(line.trim())
            .map_err(|e| format!("响应解析失败: {e}: {line}"))?;
        if resp["ok"] == true {
            Ok(resp["data"].clone())
        } else {
            Err(resp["error"].as_str().unwrap_or("未知错误").to_string())
        }
    }

    pub fn ping(&self) -> bool {
        matches!(self.call("ping", &[]), Ok(v) if v["pong"] == true)
    }
}

impl Default for Client {
    fn default() -> Self {
        Self::new()
    }
}
