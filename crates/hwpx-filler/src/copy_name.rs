//! Pure first-free copy naming shared by template files, jobs and presets.

use crate::output_name::is_reserved_device_name;

pub fn numbered_label(name: &str, number: usize) -> String {
    if number == 1 {
        name.into()
    } else {
        format!("{name} ({number})")
    }
}
pub fn numbered_file_name(name: &str, number: usize) -> String {
    if number == 1 {
        return name.into();
    }
    match name.rsplit_once('.') {
        Some((stem, suffix)) if !stem.is_empty() => format!("{stem} ({number}).{suffix}"),
        _ => format!("{name} ({number})"),
    }
}
pub fn first_free(
    mut candidate: impl FnMut(usize) -> String,
    mut taken: impl FnMut(&str) -> bool,
) -> String {
    let mut number = 1usize;
    loop {
        let name = candidate(number);
        if !taken(&name) {
            return name;
        }
        number = number
            .checked_add(1)
            .expect("copy name candidate space exhausted");
    }
}
pub fn device_safe_file_name(name: &str) -> String {
    if !is_reserved_device_name(name) {
        return name.into();
    }
    match name.split_once('.') {
        Some((head, rest)) => format!("{head}_.{rest}"),
        None => format!("{name}_"),
    }
}
