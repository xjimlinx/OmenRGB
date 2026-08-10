//! 守护进程 socket 协议（换行分隔 JSON）。

use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub struct Request {
    pub cmd: String,
    #[serde(default)]
    pub args: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct Response {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

impl Response {
    pub fn ok(data: serde_json::Value) -> Self {
        Self { ok: true, data: Some(data), error: None, hint: None }
    }

    pub fn err(error: impl Into<String>, hint: Option<String>) -> Self {
        Self { ok: false, data: None, error: Some(error.into()), hint }
    }
}
