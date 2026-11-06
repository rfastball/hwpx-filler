//! Settings JSON read-modify-write with the same-home atomic replacement contract.

use crate::atomic_file::write_bytes_atomic;
use serde_json::{Map, Value};
use std::fs;
use std::io;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

const READ_RETRIES: usize = 5;
const REPLACE_RETRIES: usize = 5;
static MUTATE_LOCK: Mutex<()> = Mutex::new(());

/// Always attempt stderr before the best-effort durable alarm channel.
pub fn alert(home: &Path, message: &str) {
    alert_with_stderr(home, message, |message| eprintln!("[hwpx] {message}"));
}

fn alert_with_stderr(home: &Path, message: &str, stderr: impl FnOnce(&str)) {
    stderr(message);
    if fs::create_dir_all(home).is_ok()
        && let Ok(mut log) = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(home.join("webapp-alerts.log"))
    {
        let _ = writeln!(
            log,
            "{} {message}",
            chrono::Local::now().format("%Y-%m-%dT%H:%M:%S")
        );
    }
}

fn parse(text: &str) -> Map<String, Value> {
    serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_default()
}
fn pause(attempt: usize) {
    thread::sleep(Duration::from_millis(50 * (attempt as u64 + 1)));
}

/// Read failures after bounded retries return defaults only after the caller's durable alarm.
pub fn read_with_alert(path: &Path, alert: impl Fn(&str)) -> io::Result<Map<String, Value>> {
    read_with_pause(path, alert, pause)
}

fn read_with_pause(
    path: &Path,
    alert: impl Fn(&str),
    mut pause: impl FnMut(usize),
) -> io::Result<Map<String, Value>> {
    let mut last_error = None;
    for attempt in 0..READ_RETRIES {
        match fs::read_to_string(path) {
            Ok(text) => return Ok(parse(&text)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Map::new()),
            Err(error) if error.kind() == io::ErrorKind::InvalidData => return Err(error),
            Err(error) => {
                last_error = Some(error);
                if attempt + 1 < READ_RETRIES {
                    pause(attempt);
                }
            }
        }
    }
    alert(&format!(
        "설정 판독 지속 실패 — 테마 등 저장값을 회수 못 하고 기본값으로 진행: {last_error:?}"
    ));
    Ok(Map::new())
}

fn read_for_update(path: &Path) -> io::Result<Map<String, Value>> {
    match fs::read_to_string(path) {
        Ok(text) => Ok(parse(&text)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(Map::new()),
        Err(error) => Err(error),
    }
}

/// A serialized update rereads on each transient sharing failure and preserves unrelated keys.
pub fn mutate(path: &Path, mutator: impl Fn(&mut Map<String, Value>)) -> io::Result<()> {
    mutate_with_pause(path, mutator, pause)
}

fn mutate_with_pause(
    path: &Path,
    mutator: impl Fn(&mut Map<String, Value>),
    mut pause: impl FnMut(usize),
) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    let _guard = MUTATE_LOCK
        .lock()
        .map_err(|_| io::Error::other("settings mutation lock poisoned"))?;
    for attempt in 0..REPLACE_RETRIES {
        let result = (|| {
            let mut data = read_for_update(path)?;
            mutator(&mut data);
            let encoded = serde_json::to_vec_pretty(&data).map_err(io::Error::other)?;
            write_bytes_atomic(path, &encoded)
        })();
        match result {
            Ok(()) => return Ok(()),
            Err(error)
                if (error.kind() == io::ErrorKind::PermissionDenied
                    // Rust leaves Windows sharing/lock violations uncategorized.
                    || cfg!(windows) && matches!(error.raw_os_error(), Some(32 | 33)))
                    && attempt + 1 < REPLACE_RETRIES =>
            {
                pause(attempt)
            }
            Err(error) => return Err(error),
        }
    }
    unreachable!("last attempt returns")
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{alert_with_stderr, mutate, mutate_with_pause, read_with_alert, read_with_pause};
    use serde_json::json;
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn alert_keeps_stderr_when_log_creation_or_append_is_unavailable() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/settings-alert-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&root).unwrap();
        let mut messages = Vec::new();
        for message in ["첫 경보", "두 번째 경보"] {
            alert_with_stderr(&root, message, |text| messages.push(text.to_owned()));
        }
        assert_eq!(messages, ["첫 경보", "두 번째 경보"]);
        let log = fs::read_to_string(root.join("webapp-alerts.log")).unwrap();
        let lines = log.lines().collect::<Vec<_>>();
        assert_eq!(lines.len(), 2);
        for (line, message) in lines.iter().zip(&messages) {
            let (stamp, body) = line.split_once(' ').unwrap();
            chrono::NaiveDateTime::parse_from_str(stamp, "%Y-%m-%dT%H:%M:%S").unwrap();
            assert_eq!(body, message);
        }
        let blocker = root.join("file");
        fs::write(&blocker, b"KEEP").unwrap();
        let bad_log = root.join("blocked-log");
        fs::create_dir_all(bad_log.join("webapp-alerts.log")).unwrap();
        for home in [blocker.join("home"), bad_log] {
            let mut reported = None;
            alert_with_stderr(&home, "경보 본문", |text| {
                reported = Some(text.to_owned())
            });
            assert_eq!(reported.as_deref(), Some("경보 본문"));
        }
        assert_eq!(fs::read(&blocker).unwrap(), b"KEEP");
        assert_eq!(
            fs::read_to_string(root.join("webapp-alerts.log")).unwrap(),
            log
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn update_preserves_unrelated_keys_and_recovers_corrupt_json() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-settings-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("settings.json");
        fs::write(&path, r#"{"theme":"dark","keep":7}"#).unwrap();
        mutate(&path, |settings| {
            settings.insert("theme".into(), json!("light"));
        })
        .unwrap();
        let data = read_with_alert(&path, |_| panic!("valid settings must not alarm")).unwrap();
        assert_eq!(data.get("keep"), Some(&json!(7)));
        assert_eq!(data.get("theme"), Some(&json!("light")));
        fs::write(&path, "{잘림").unwrap();
        mutate(&path, |settings| {
            settings.insert("theme".into(), json!("system"));
        })
        .unwrap();
        assert_eq!(
            read_with_alert(&path, |_| panic!("recovered settings must not alarm"))
                .unwrap()
                .len(),
            1
        );
        assert!(
            fs::read_dir(&root)
                .unwrap()
                .all(|entry| entry.unwrap().path() == path)
        );
        fs::write(&path, [0xff]).unwrap();
        assert_eq!(
            read_with_pause(
                &path,
                |_| panic!("invalid encoding must propagate"),
                |_| panic!("invalid encoding must not retry")
            )
            .unwrap_err()
            .kind(),
            std::io::ErrorKind::InvalidData
        );
        assert!(
            mutate_with_pause(
                &path,
                |_| panic!("unreadable file must not be replaced"),
                |_| panic!("invalid encoding must not retry")
            )
            .is_err()
        );
        assert_eq!(fs::read(&path).unwrap(), [0xff]);
        fs::remove_file(&path).unwrap();
        assert!(
            read_with_pause(
                &path,
                |_| panic!("missing file must not alarm"),
                |_| panic!("missing file must not retry")
            )
            .unwrap()
            .is_empty()
        );
        fs::create_dir(&path).unwrap();
        let alarms = std::cell::RefCell::new(Vec::new());
        let mut waits = Vec::new();
        assert!(
            read_with_pause(
                &path,
                |message| alarms.borrow_mut().push(message.to_owned()),
                |attempt| waits.push(attempt)
            )
            .unwrap()
            .is_empty()
        );
        assert_eq!(waits, [0, 1, 2, 3]);
        assert_eq!(alarms.borrow().len(), 1);
        assert!(alarms.borrow()[0].contains("설정 판독 지속 실패"));
        assert!(
            mutate_with_pause(&path, |_| panic!("failed read must not erase keys"), |_| {})
                .is_err()
        );
        assert!(path.is_dir());
        fs::remove_dir(&path).unwrap();
        #[cfg(windows)]
        assert_windows_sharing_retries(&path);
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    fn assert_windows_sharing_retries(path: &Path) {
        use std::os::windows::fs::OpenOptionsExt;

        fs::write(path, r#"{"theme":"light","keep":7}"#).unwrap();
        let mut held = Some(
            fs::OpenOptions::new()
                .read(true)
                .share_mode(0)
                .open(path)
                .unwrap(),
        );
        let mut waits = Vec::new();
        let saved = read_with_pause(
            path,
            |_| panic!("transient read must not alarm"),
            |attempt| {
                waits.push(attempt);
                if attempt == 1 {
                    held.take();
                }
            },
        )
        .unwrap();
        assert_eq!(waits, [0, 1]);
        assert_eq!(saved["theme"], "light");
        let mut held = Some(
            fs::OpenOptions::new()
                .read(true)
                .share_mode(0)
                .open(path)
                .unwrap(),
        );
        let mut waits = Vec::new();
        mutate_with_pause(
            path,
            |data| {
                data.insert("theme".into(), json!("dark"));
            },
            |attempt| {
                waits.push(attempt);
                if attempt == 1 {
                    held.take();
                }
            },
        )
        .unwrap();
        assert_eq!(waits, [0, 1]);
        let mut held = Some(
            fs::OpenOptions::new()
                .read(true)
                .share_mode(1)
                .open(path)
                .unwrap(),
        );
        let mut waits = Vec::new();
        mutate_with_pause(
            path,
            |data| {
                data.insert("theme".into(), json!("system"));
            },
            |attempt| {
                waits.push(attempt);
                held.take();
                fs::write(path, r#"{"theme":"dark","keep":42}"#).unwrap();
            },
        )
        .unwrap();
        assert_eq!(waits, [0]);
        let saved = read_with_alert(path, |_| panic!("read must succeed")).unwrap();
        assert_eq!(saved["theme"], "system");
        assert_eq!(
            saved["keep"], 42,
            "retry must reread the other writer's settings"
        );
        let before = fs::read(path).unwrap();
        let held = fs::OpenOptions::new()
            .read(true)
            .share_mode(1)
            .open(path)
            .unwrap();
        let mut waits = Vec::new();
        let error = mutate_with_pause(
            path,
            |data| {
                data.clear();
            },
            |attempt| waits.push(attempt),
        )
        .unwrap_err();
        assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
        assert_eq!(waits, [0, 1, 2, 3]);
        drop(held);
        assert_eq!(fs::read(path).unwrap(), before);
        assert!(
            fs::read_dir(path.parent().unwrap())
                .unwrap()
                .all(|entry| entry.unwrap().path() == path)
        );
    }
}
