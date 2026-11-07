use super::*;

struct CommandOutput {
    success: bool,
    stdout: String,
    stderr: String,
}
fn command_output(command: &mut Command, role: &str) -> Result<CommandOutput> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| fail(format!("{role} failed")))?;
    let mut stdout = child.stdout.take().expect("piped stdout");
    let mut stderr = child.stderr.take().expect("piped stderr");
    let output = thread::spawn(move || {
        let mut data = Vec::new();
        stdout.read_to_end(&mut data).map(|_| data)
    });
    let errors = thread::spawn(move || {
        let mut data = Vec::new();
        stderr.read_to_end(&mut data).map(|_| data)
    });
    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if started.elapsed() < Duration::from_secs(30) => {
                thread::sleep(Duration::from_millis(10))
            }
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(fail(format!("{role} failed")));
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(fail(format!("{role} failed")));
            }
        }
    };
    let stdout = output
        .join()
        .map_err(|_| fail(format!("{role} failed")))?
        .map_err(|_| fail(format!("{role} failed")))?;
    let stderr = errors
        .join()
        .map_err(|_| fail(format!("{role} failed")))?
        .map_err(|_| fail(format!("{role} failed")))?;
    Ok(CommandOutput {
        success: status.success(),
        stdout: String::from_utf8_lossy(&stdout).into_owned(),
        stderr: String::from_utf8_lossy(&stderr).into_owned(),
    })
}
fn git_output(repo: &Path, args: &[&str], role: &str) -> Result<String> {
    let output = command_output(Command::new("git").arg("-C").arg(repo).args(args), role)?;
    if !output.success {
        return Err(fail(format!("{role} failed")));
    }
    Ok(output.stdout)
}
pub(super) fn current_git_commit(repo: &Path) -> Result<String> {
    let commit = git_output(repo, &["rev-parse", "HEAD"], "Git commit lookup")?
        .trim()
        .to_owned();
    if commit.len() != 40
        || !commit
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(fail("Git commit lookup returned an invalid full SHA"));
    }
    Ok(commit)
}
pub(super) fn assert_source_inputs_clean(repo: &Path) -> Result<()> {
    let mut args = vec![
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "frontend",
        "vendor/rhwp",
    ];
    args.extend(SOURCE_CONFIG);
    let dirty = git_output(repo, &args, "Git source-input status lookup")?;
    if !dirty.is_empty() {
        let offenders = dirty_paths(&dirty).join(", ");
        return Err(fail(format!(
            "web build inputs are not committed; refusing to seal a dirty source tree: {offenders}"
        )));
    }
    Ok(())
}
pub(super) fn dirty_paths(porcelain: &str) -> Vec<&str> {
    porcelain
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| line.get(3..).unwrap_or(line))
        .collect()
}
fn command_version(command: &Path, repo: &Path, role: &str) -> Result<String> {
    let output = command_output(
        Command::new(command).arg("--version").current_dir(repo),
        &format!("{role} version command"),
    )?;
    let combined = format!("{}\n{}", output.stdout, output.stderr);
    let match_version = regex(r"(?m)(?:^|[^\d.])v?(\d+\.\d+\.\d+)(?:[^\d.]|$)");
    if !output.success {
        return Err(fail(format!(
            "{role} version command failed: {}",
            command.display()
        )));
    }
    match_version
        .captures(&combined)
        .map(|capture| capture[1].to_owned())
        .ok_or_else(|| {
            fail(format!(
                "{role} version command failed: {}",
                command.display()
            ))
        })
}
pub(super) fn detect_toolchain(
    repo: &Path,
    node: Option<&Path>,
    npm: Option<&Path>,
    vite: Option<&Path>,
) -> Result<Toolchain> {
    let expected = declared_toolchain(repo)?;
    let node = command_version(node.unwrap_or(Path::new("node")), repo, "Node")?;
    let npm_default = if cfg!(windows) { "npm.cmd" } else { "npm" };
    let npm = command_version(npm.unwrap_or(Path::new(npm_default)), repo, "npm")?;
    let vite_default = repo.join(if cfg!(windows) {
        "node_modules/.bin/vite.cmd"
    } else {
        "node_modules/.bin/vite"
    });
    let vite = command_version(vite.unwrap_or(&vite_default), repo, "Vite")?;
    let actual = Toolchain { node, npm, vite };
    if actual != expected {
        return Err(fail(format!(
            "actual web toolchain does not match exact pins: expected={expected:?} actual={actual:?}"
        )));
    }
    Ok(actual)
}
