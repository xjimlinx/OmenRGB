//! omenrgb — 命令行客户端（通过守护进程读写键盘灯效）。

use std::env;
use std::process::ExitCode;

use omenrgb_core::client::Client;
use omenrgb_core::ZONE_NAMES;

fn usage() -> ! {
    eprintln!(
        "omenrgb - HP OMEN 键盘 RGB 控制（经 omenrgbd 守护进程）\n\
\n\
用法:\n\
  omenrgb status                     显示状态\n\
  omenrgb set-all RRGGBB             全部区域设为同一颜色\n\
  omenrgb set-zone N RRGGBB          设置单个区域 (0-3)\n\
  omenrgb brightness 0-100           亮度\n\
  omenrgb animate NAME               动画 (ghosting/ripple/wave/omenx/\n\
                                      raindrop/audiopulse/linestreak/starlight/galaxy)\n\
  omenrgb kbam                       读取键盘模式寄存器\n\
  omenrgb zones                      显示分区名\n"
    );
    std::process::exit(2);
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        usage();
    }
    let client = Client::new();
    let cmd = args[0].as_str();
    let rest: Vec<&str> = args[1..].iter().map(String::as_str).collect();

    let result = match cmd {
        "status" => client.call("status", &[]).map(|v| {
            println!("后端: {}", v["backend"].as_str().unwrap_or("?"));
            let zones = v["zones"].as_array().map(|z| {
                z.iter()
                    .map(|x| x.as_str().unwrap_or("?").to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            }).unwrap_or_default();
            println!("区域颜色: {zones}");
            println!("亮度: {}%", v["brightness"].as_i64().unwrap_or(0));
            if let Some(kbam) = v["kbam"].as_u64() {
                println!("键盘模式 (KBAM): {kbam}");
            }
        }),
        "set-all" => {
            let rgb = rest.first().unwrap_or_else(|| usage());
            client.call("set_all", &[rgb]).map(|v| {
                println!("已应用 #{} 到全部区域", v["applied"].as_str().unwrap_or(""));
            })
        }
        "set-zone" => {
            let zone = rest.first().unwrap_or_else(|| usage());
            let rgb = rest.get(1).unwrap_or_else(|| usage());
            client.call("set_zone", &[zone, rgb]).map(|v| {
                println!("已应用 #{} 到{}", v["applied"].as_str().unwrap_or(""), ZONE_NAMES[zone.parse::<usize>().unwrap_or(0)]);
            })
        }
        "brightness" => {
            let level = rest.first().unwrap_or_else(|| usage());
            client.call("brightness", &[level]).map(|v| {
                println!("亮度已设为 {}%", v["brightness"].as_i64().unwrap_or(0));
            })
        }
        "animate" => {
            let name = rest.first().unwrap_or_else(|| usage());
            client.call("animate", &[name]).map(|v| {
                println!("已发送动画: {}", v["animation"].as_str().unwrap_or(""));
            })
        }
        "kbam" => client.call("kbam", &[]).map(|v| {
            println!("KBAM = {}", v["kbam"].as_u64().unwrap_or(0));
        }),
        "zones" => {
            for (i, name) in ZONE_NAMES.iter().enumerate() {
                println!("{i}: {name}");
            }
            Ok(())
        }
        _ => usage(),
    };

    match result {
        Ok(_) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("错误: {e}");
            eprintln!("提示: 请确认守护进程已安装并运行：sudo ./install-systemd-service.sh");
            ExitCode::FAILURE
        }
    }
}
