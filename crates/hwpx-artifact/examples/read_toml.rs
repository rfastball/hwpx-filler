//! Parse one TOML snapshot from stdin for Node-based build tools.

use std::io::Read;

fn main() {
    if std::env::args_os().len() != 1 {
        eprintln!("usage: read_toml < FILE.toml");
        std::process::exit(2);
    }
    let mut source = String::new();
    let result = std::io::stdin()
        .read_to_string(&mut source)
        .map_err(|error| error.to_string())
        .and_then(|_| toml::from_str::<toml::Value>(&source).map_err(|error| error.to_string()))
        .and_then(|value| serde_json::to_string(&value).map_err(|error| error.to_string()));
    match result {
        Ok(json) => println!("{json}"),
        Err(error) => {
            eprintln!("TOML parse failed: {error}");
            std::process::exit(1);
        }
    }
}
