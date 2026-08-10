//! omenrgbd — OMEN RGB 灯效守护进程（root，Unix socket）。

use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use omenrgb_core::anim::{custom_anim_frame, custom_anim_names};
use omenrgb_core::backend::Backend;
use omenrgb_core::payload;
use omenrgb_core::proto::{Request, Response};
use omenrgb_core::{
    wmi, CMDT_LIGHTBAR_MAILBOX, CMD_BACKLIGHT,
};

static STOP: AtomicBool = AtomicBool::new(false);

/// 正在运行的主机驱动自定义动画（帧线程）。
struct AnimControl {
    stop: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<()>>,
}

type AnimCtl = Arc<Mutex<Option<AnimControl>>>;

/// 停止自定义动画线程并等待其退出；返回是否曾有一个在运行。
fn stop_custom_anim(ctl: &Mutex<Option<AnimControl>>) -> bool {
    let mut guard = ctl.lock().unwrap();
    if let Some(mut c) = guard.take() {
        c.stop.store(true, Ordering::Relaxed);
        if let Some(h) = c.handle.take() {
            let _ = h.join();
        }
        true
    } else {
        false
    }
}

/// 解析 6 位 RRGGBB；非法时回退到 OMEN 粉（FF2C74），动画基础色容错处理。
fn parse_rgb(s: &str) -> [u8; 3] {
    let s = s.trim().trim_start_matches('#');
    let ok = s.len() == 6 && s.bytes().all(|b| b.is_ascii_hexdigit());
    if !ok {
        return [0xFF, 0x2C, 0x74];
    }
    [
        u8::from_str_radix(&s[0..2], 16).unwrap_or(0xFF),
        u8::from_str_radix(&s[2..4], 16).unwrap_or(0x2C),
        u8::from_str_radix(&s[4..6], 16).unwrap_or(0x74),
    ]
}

/// 启动主机驱动自定义动画：30fps 循环写静态色载荷。
/// 先发一帧静态色把固件动画切回静态模式，再进入帧循环。
fn start_custom_anim(
    ctl: &Mutex<Option<AnimControl>>,
    backend: &mut Backend,
    name: &str,
    base: &str,
    speed: f32,
) -> Result<(), String> {
    if !custom_anim_names().contains(&name) {
        return Err(format!("未知自定义动画: {name}"));
    }
    stop_custom_anim(ctl);
    let brightness = backend.brightness();
    let colors = std::array::from_fn(|_| base.to_string());
    let p = payload::static_payload(&colors, brightness)?;
    wmi::wmaa(CMD_BACKLIGHT, CMDT_LIGHTBAR_MAILBOX, &p, 8)?;
    backend.set_custom_anim(Some(name));

    let stop = Arc::new(AtomicBool::new(false));
    let stop2 = Arc::clone(&stop);
    let name2 = name.to_string();
    let base_rgb = parse_rgb(base);
    let handle = thread::spawn(move || {
        let fps: f32 = 30.0;
        let interval = Duration::from_secs_f32(1.0 / fps);
        let mut next = Instant::now();
        let mut t = 0.0f32;
        while !stop2.load(Ordering::Relaxed) {
            let frame = custom_anim_frame(&name2, t, base_rgb, speed);
            let strs: [String; 4] = frame.map(|c| format!("{:02X}{:02X}{:02X}", c[0], c[1], c[2]));
            if let Ok(p) = payload::lightbar_payload(&strs, 0, brightness, 1) {
                // 静默写入：每帧都打日志会刷爆 journald
                let _ = wmi::wmaa_quiet(CMD_BACKLIGHT, CMDT_LIGHTBAR_MAILBOX, &p, 8);
            }
            t += 1.0 / fps;
            next += interval;
            let wait = next.saturating_duration_since(Instant::now());
            if !wait.is_zero() {
                thread::sleep(wait);
            }
        }
    });
    *ctl.lock().unwrap() = Some(AnimControl {
        stop,
        handle: Some(handle),
    });
    Ok(())
}

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

fn dispatch(
    backend: &mut Backend,
    anim_ctl: &Mutex<Option<AnimControl>>,
    req: Request,
) -> Result<serde_json::Value, String> {
    let cmd = req.cmd.as_str();
    let args = req.args.as_slice();
    match cmd {
        "ping" => Ok(serde_json::json!({"pong": true})),
        "status" => backend.get_state().map(|s| serde_json::to_value(s).unwrap()),
        "set_all" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            let rgb = args.first().ok_or("缺少颜色参数")?;
            backend.set_all(rgb, None).map(|_| serde_json::json!({"applied": rgb}))
        }
        "set_zone" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            let zone = args
                .first()
                .ok_or("缺少分区参数")?
                .parse::<usize>()
                .map_err(|_| "分区必须是 0-3")?;
            let rgb = args.get(1).ok_or("缺少颜色参数")?;
            backend.set_zone(zone, rgb, None).map(|_| serde_json::json!({"applied": rgb}))
        }
        "brightness" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            let level = args
                .first()
                .ok_or("缺少亮度参数")?
                .parse::<u8>()
                .map_err(|_| "亮度必须是 0-100")?;
            backend.set_brightness(level).map(|_| serde_json::json!({"brightness": level}))
        }
        "animate" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            let name = args.first().ok_or("缺少动画名")?;
            backend.animate(name).map(|_| serde_json::json!({"animation": name}))
        }
        "static" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            backend
                .static_colors(None)
                .map(|_| serde_json::json!({"mode": "static"}))
        }
        // 主机驱动自定义动画
        "anim_start" => {
            let name = args.first().ok_or("缺少动画名")?.to_string();
            let base = args
                .get(1)
                .cloned()
                .unwrap_or_else(|| "FF2C74".to_string());
            let speed = args
                .get(2)
                .and_then(|s| s.parse::<f32>().ok())
                .unwrap_or(1.0)
                .clamp(0.2, 4.0);
            start_custom_anim(anim_ctl, backend, &name, &base, speed)
                .map(|_| serde_json::json!({"animation": name, "base": base, "speed": speed}))
        }
        "anim_stop" => {
            let was = stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            backend
                .static_colors(None)
                .map(|_| serde_json::json!({"stopped": was}))
        }
        "profile_save" => {
            let name = args.first().ok_or("缺少方案名")?;
            backend.profile_save(name).map(|_| serde_json::json!({"saved": name}))
        }
        "profile_load" => {
            stop_custom_anim(anim_ctl);
            backend.set_custom_anim(None);
            let name = args.first().ok_or("缺少方案名")?;
            let s = backend.profile_load(name)?;
            Ok(serde_json::json!({
                "loaded": name,
                "colors": s.colors,
                "brightness": s.brightness,
                "animation": s.animation,
            }))
        }
        "profile_list" => {
            let list: Vec<_> = backend
                .profile_list()
                .into_iter()
                .map(|(name, s)| {
                    serde_json::json!({
                        "name": name,
                        "colors": s.colors,
                        "brightness": s.brightness,
                        "animation": s.animation,
                    })
                })
                .collect();
            Ok(serde_json::json!({"profiles": list}))
        }
        "profile_delete" => {
            let name = args.first().ok_or("缺少方案名")?;
            backend.profile_delete(name).map(|_| serde_json::json!({"deleted": name}))
        }
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

fn handle_conn(
    mut stream: UnixStream,
    backend: Arc<Mutex<Backend>>,
    anim_ctl: AnimCtl,
) {
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
        match dispatch(&mut guard, &anim_ctl, req) {
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
    let anim_ctl: AnimCtl = Arc::new(Mutex::new(None));
    // 启动时恢复上次保存的灯效状态（颜色/亮度/动画）
    if let Err(e) = backend.lock().unwrap().restore() {
        eprintln!("[omenrgbd] 状态恢复失败: {e}");
    }

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
                let a = Arc::clone(&anim_ctl);
                thread::spawn(move || handle_conn(s, b, a));
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
