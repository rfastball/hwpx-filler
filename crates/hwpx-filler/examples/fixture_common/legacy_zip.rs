//! Deterministic Python zipfile-compatible ZIP layout for frozen example assets.
//! This dev-only writer is intentionally separate from the production package writer.
//! The pinned crates.io libz-sys 1.1.30 package vendors zlib 1.3.2; Cargo.lock
//! fixes its source checksum. Upstream zlib 1.3.2 source SHA-256 is
//! bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16
//! (https://zlib.net/fossils/zlib-1.3.2.tar.gz, zlib license).

use hwpx_core::package::PackageEntry;
use std::error::Error;

fn little16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn little32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn raw_deflate(data: &[u8]) -> Result<Vec<u8>, Box<dyn Error>> {
    let input_len = u32::try_from(data.len())?;
    // Python 3.13 zipfile uses zlib.compressobj(-1, DEFLATED, -15), then flush().
    // libz-sys 1.1.30 vendors the pinned zlib 1.3.2 used by the frozen assets.
    let version = unsafe { std::ffi::CStr::from_ptr(libz_sys::zlibVersion()) };
    if version.to_bytes() != b"1.3.2" {
        return Err(format!("unexpected fixture zlib version: {version:?}").into());
    }
    let capacity = unsafe { libz_sys::compressBound(input_len as _) }
        .checked_add(1024)
        .ok_or("fixture compressed capacity overflow")?;
    let mut output = vec![0u8; usize::try_from(capacity)?];
    let output_len = u32::try_from(output.len())?;
    // zlib accepts a zeroed C stream and fills the allocator callbacks on init.
    // Keep it uninitialized in Rust until those non-null function pointers exist.
    let mut stream = std::mem::MaybeUninit::<libz_sys::z_stream>::zeroed();
    let init = unsafe {
        libz_sys::deflateInit2_(
            stream.as_mut_ptr(),
            libz_sys::Z_DEFAULT_COMPRESSION,
            libz_sys::Z_DEFLATED,
            -15,
            8,
            libz_sys::Z_DEFAULT_STRATEGY,
            libz_sys::zlibVersion(),
            i32::try_from(std::mem::size_of::<libz_sys::z_stream>())?,
        )
    };
    if init != libz_sys::Z_OK {
        return Err(format!("fixture deflate initialization failed: {init}").into());
    }
    // zlib keeps a pointer to the stream in its internal state; do not move it.
    let stream = unsafe { stream.assume_init_mut() };
    stream.next_in = data.as_ptr().cast_mut();
    stream.avail_in = input_len;
    stream.next_out = output.as_mut_ptr();
    stream.avail_out = output_len;
    let written = unsafe { libz_sys::deflate(stream, libz_sys::Z_NO_FLUSH) };
    let finished = if written == libz_sys::Z_OK {
        unsafe { libz_sys::deflate(stream, libz_sys::Z_FINISH) }
    } else {
        written
    };
    let end = unsafe { libz_sys::deflateEnd(stream) };
    if finished != libz_sys::Z_STREAM_END || end != libz_sys::Z_OK {
        return Err(format!("fixture deflate failed: {finished}/{end}").into());
    }
    output.truncate(usize::try_from(stream.total_out)?);
    Ok(output)
}

/// One entry's precomputed fixed-layout fields, shared by its local header and its
/// central-directory record.
struct EntryLayout<'a> {
    name: &'a [u8],
    name_len: u16,
    plain_len: u32,
    compressed: Vec<u8>,
    compressed_len: u32,
    crc: u32,
    method: u16,
    offset: u32,
}
fn entry_layout<'a>(
    entry: &'a PackageEntry,
    offset: u32,
) -> Result<EntryLayout<'a>, Box<dyn Error>> {
    if !entry.name.is_ascii() || entry.name.is_empty() || entry.name.contains('\\') {
        return Err(format!("unsupported fixture ZIP name: {}", entry.name).into());
    }
    let name = entry.name.as_bytes();
    let name_len = u16::try_from(name.len())?;
    let plain_len = u32::try_from(entry.data.len())?;
    let compressed = if entry.stored {
        entry.data.clone()
    } else {
        raw_deflate(&entry.data)?
    };
    let compressed_len = u32::try_from(compressed.len())?;
    let crc =
        unsafe { libz_sys::crc32(0, entry.data.as_ptr(), u32::try_from(entry.data.len())?) } as u32;
    let method = if entry.stored { 0 } else { 8 };
    Ok(EntryLayout {
        name,
        name_len,
        plain_len,
        compressed,
        compressed_len,
        crc,
        method,
        offset,
    })
}
/// Python ZipInfo defaults: made/needed 20, DOS epoch, no extra/comment,
/// mode 0600 in external attributes, seekable local header without descriptor.
fn write_local_header(archive: &mut Vec<u8>, entry: &EntryLayout<'_>) {
    little32(archive, 0x0403_4b50);
    little16(archive, 20);
    little16(archive, 0);
    little16(archive, entry.method);
    little16(archive, 0);
    little16(archive, 0x21);
    little32(archive, entry.crc);
    little32(archive, entry.compressed_len);
    little32(archive, entry.plain_len);
    little16(archive, entry.name_len);
    little16(archive, 0);
    archive.extend_from_slice(entry.name);
    archive.extend_from_slice(&entry.compressed);
}
fn write_central_directory_record(directory: &mut Vec<u8>, entry: &EntryLayout<'_>) {
    little32(directory, 0x0201_4b50);
    little16(directory, 20);
    little16(directory, 20);
    little16(directory, 0);
    little16(directory, entry.method);
    little16(directory, 0);
    little16(directory, 0x21);
    little32(directory, entry.crc);
    little32(directory, entry.compressed_len);
    little32(directory, entry.plain_len);
    little16(directory, entry.name_len);
    little16(directory, 0);
    little16(directory, 0);
    little16(directory, 0);
    little16(directory, 0);
    little32(directory, 0o600 << 16);
    little32(directory, entry.offset);
    directory.extend_from_slice(entry.name);
}
fn write_end_of_central_directory(
    archive: &mut Vec<u8>,
    count: u16,
    directory_size: u32,
    directory_offset: u32,
) {
    little32(archive, 0x0605_4b50);
    little16(archive, 0);
    little16(archive, 0);
    little16(archive, count);
    little16(archive, count);
    little32(archive, directory_size);
    little32(archive, directory_offset);
    little16(archive, 0);
}

pub fn write(entries: &[PackageEntry]) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut archive = Vec::new();
    let mut directory = Vec::new();
    for entry in entries {
        let layout = entry_layout(entry, u32::try_from(archive.len())?)?;
        write_local_header(&mut archive, &layout);
        write_central_directory_record(&mut directory, &layout);
    }
    let directory_offset = u32::try_from(archive.len())?;
    let directory_size = u32::try_from(directory.len())?;
    let count = u16::try_from(entries.len())?;
    archive.extend_from_slice(&directory);
    write_end_of_central_directory(&mut archive, count, directory_size, directory_offset);
    Ok(archive)
}
