fn main() {
    println!("cargo:rerun-if-changed=tauri.conf.json");
    #[cfg(feature = "shell")]
    tauri_build::build();
}
