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

pub fn write(entries: &[PackageEntry]) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut archive = Vec::new();
    let mut directory = Vec::new();
    for entry in entries {
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
        let offset = u32::try_from(archive.len())?;
        let crc =
            unsafe { libz_sys::crc32(0, entry.data.as_ptr(), u32::try_from(entry.data.len())?) }
                as u32;
        let method = if entry.stored { 0 } else { 8 };

        // Python ZipInfo defaults: made/needed 20, DOS epoch, no extra/comment,
        // mode 0600 in external attributes, seekable local header without descriptor.
        little32(&mut archive, 0x0403_4b50);
        little16(&mut archive, 20);
        little16(&mut archive, 0);
        little16(&mut archive, method);
        little16(&mut archive, 0);
        little16(&mut archive, 0x21);
        little32(&mut archive, crc);
        little32(&mut archive, compressed_len);
        little32(&mut archive, plain_len);
        little16(&mut archive, name_len);
        little16(&mut archive, 0);
        archive.extend_from_slice(name);
        archive.extend_from_slice(&compressed);

        little32(&mut directory, 0x0201_4b50);
        little16(&mut directory, 20);
        little16(&mut directory, 20);
        little16(&mut directory, 0);
        little16(&mut directory, method);
        little16(&mut directory, 0);
        little16(&mut directory, 0x21);
        little32(&mut directory, crc);
        little32(&mut directory, compressed_len);
        little32(&mut directory, plain_len);
        little16(&mut directory, name_len);
        little16(&mut directory, 0);
        little16(&mut directory, 0);
        little16(&mut directory, 0);
        little16(&mut directory, 0);
        little32(&mut directory, 0o600 << 16);
        little32(&mut directory, offset);
        directory.extend_from_slice(name);
    }
    let directory_offset = u32::try_from(archive.len())?;
    let directory_size = u32::try_from(directory.len())?;
    let count = u16::try_from(entries.len())?;
    archive.extend_from_slice(&directory);
    little32(&mut archive, 0x0605_4b50);
    little16(&mut archive, 0);
    little16(&mut archive, 0);
    little16(&mut archive, count);
    little16(&mut archive, count);
    little32(&mut archive, directory_size);
    little32(&mut archive, directory_offset);
    little16(&mut archive, 0);
    Ok(archive)
}
