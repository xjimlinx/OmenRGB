//! omenrgbd — OMEN RGB 灯效守护进程（root，Unix socket）。

use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

use omenrgb_core::backend::Backend;
use omenrgb_core::proto::{Request, Response};

static STOP: AtomicBool = AtomicBool::new(false);

fn sock_path() -> String {
    env::var("OMENRGB_SOCK_PATH").unwrap_or_else(|_| {
        let dir = env::var("OMENRGB_SOCK_DIR").unwrap_or_else(|_| "/run/omenrgb".into());
        format!("{dir}/control.sock")
    })
}

fn chown_socket(path: &str) {
    let user = env::var("OMENRGB_SOCK_USER").unwrap_or_default();
    if user.is_empty() {
        return;
    }
    unsafe {
        let cuser = std::ffi::CString::new(user.as_str()).unwrap();
        let pw = libc::getpwnam(cuser.as_ptr());
        if pw.is_null() {
            return;
        }
        let uid = (*pw).pw_uid;
        let gid = match env::var("OMENRGB_SOCK_GROUP") {
            Ok(group) if !group.is_empty() => {
                let cgroup = std::ffi::CString::new(group.as_str()).unwrap();
                let gr = libc::getgrnam(cgroup.as_ptr());
                if gr.is_null() {
                    (*pw).pw_gid
                } else {
                    (*gr).gr_gid
                }
            }
            _ => (*pw).pw_gid,
        };
        let cpath = std::ffi::CString::new(path).unwrap();
        libc::chown(cpath.as_ptr(), uid, gid);
    }
}

fn dispatch(backend: &mut Backend, req: Request) -> Result<serde_json::Value, String> {
    let cmd = req.cmd.as_str();
    let args = req.args.as_slice();
    match cmd {
        "ping" => Ok(serde_json::json!({"pong": true})),
        "status" => backend.get_state().map(|s| serde_json::to_value(s).unwrap()),
        "set_all" => {
            let rgb = args.first().ok_or("缺少颜色参数")?;
            backend.set_all(rgb, None).map(|_| serde_json::json!({"applied": rgb}))
        }
        "set_zone" => {
            let zone = args
                .first()
                .ok_or("缺少分区参数")?
                .parse::<usize>()
                .map_err(|_| "分区必须是 0-3")?;
            let rgb = args.get(1).ok_or("缺少颜色参数")?;
            backend.set_zone(zone, rgb, None).map(|_| serde_json::json!({"applied": rgb}))
        }
        "brightness" => {
            let level = args
                .first()
                .ok_or("缺少亮度参数")?
                .parse::<u8>()
                .map_err(|_| "亮度必须是 0-100")?;
            backend.set_brightness(level).map(|_| serde_json::json!({"brightness": level}))
        }
        "animate" => {
            let name = args.first().ok_or("缺少动画名")?;
            backend.animate(name).map(|_| serde_json::json!({"animation": name}))
        }
        "static" => backend
            .static_colors(None)
            .map(|_| serde_json::json!({"mode": "static"})),
        "kbam" => match omenrgb_core::kbam::read_kbam() {
            Ok(v) => Ok(serde_json::json!({"kbam": v})),
            Err(e) => Err(e),
        },
        // 诊断：直接写 EC 亮度寄存器（LBRT，0x05），用于实测三档亮度取值
        "lbrt" => {
            let value = args
                .first()
                .ok_or("缺少 LBRT 参数")?
                .parse::<u8>()
                .map_err(|_| "LBRT 必须是 0-255")?;
            omenrgb_core::wmi::wmaa(
                omenrgb_core::CMD_BACKLIGHT,
                omenrgb_core::CMDT_SET_BRIGHTNESS,
                &[value],
                1,
            )?;
            let rb = omenrgb_core::wmi::wmaa(
                omenrgb_core::CMD_BACKLIGHT,
                omenrgb_core::CMDT_GET_BRIGHTNESS,
                &[],
                4,
            )?;
            Ok(serde_json::json!({
                "lbrt": value,
                "readback": rb.first().copied().unwrap_or(0),
            }))
        }
        other => Err(format!("未知命令: {other}")),
    }
}

fn handle_conn(mut stream: UnixStream, backend: Arc<Mutex<Backend>>) {
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    let mut line = String::new();
    if reader.read_line(&mut line).is_err() || line.trim().is_empty() {
        return;
    }
    let req: Request = match serde_json::from_str(line.trim()) {
        Ok(r) => r,
        Err(e) => {
            let resp = Response::err(format!("请求不是合法 JSON: {e}"), None);
            let _ = writeln!(stream, "{}", serde_json::to_string(&resp).unwrap());
            return;
        }
    };
    let resp = {
        let mut guard = backend.lock().unwrap();
        match dispatch(&mut guard, req) {
            Ok(data) => Response::ok(data),
            Err(e) => Response::err(e, Some("守护进程需要 root；请确认以 systemd 服务运行。".into())),
        }
    };
    let _ = writeln!(stream, "{}", serde_json::to_string(&resp).unwrap());
}

fn main() {
    let path = sock_path();
    if let Some(parent) = std::path::Path::new(&path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::remove_file(&path);

    let listener = match UnixListener::bind(&path) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("无法绑定 {path}: {e}");
            std::process::exit(1);
        }
    };
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, std::fs::Permissions::from_mode(0o660));
    }
    chown_socket(&path);
    listener
        .set_nonblocking(true)
        .expect("设置非阻塞失败");
    println!("omenrgbd 监听 {path}");

    let backend = Arc::new(Mutex::new(Backend::new()));

    unsafe {
        libc::signal(libc::SIGTERM, handle_signal as libc::sighandler_t);
        libc::signal(libc::SIGINT, handle_signal as libc::sighandler_t);
    }

    loop {
        if STOP.load(Ordering::Relaxed) {
            break;
        }
        match listener.accept() {
            Ok((s, _)) => {
                let b = Arc::clone(&backend);
                thread::spawn(move || handle_conn(s, b));
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(_) => {
                thread::sleep(std::time::Duration::from_millis(20));
            }
        }
    }
    let _ = fs::remove_file(&path);
}

extern "C" fn handle_signal(_sig: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}
