use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

static ARTIFACT_SEQUENCE: AtomicU64 = AtomicU64::new(0);

const VALID_PRESETS: &[&str] = &[
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
];

pub struct FfmpegVideoRecorder {
    child: Child,
    stdin: Option<ChildStdin>,
    output_path: PathBuf,
    temporary_path: PathBuf,
    expected_frame_bytes: usize,
    frame_count: u32,
    encoding_finished: bool,
    published: bool,
}

impl FfmpegVideoRecorder {
    #[allow(clippy::too_many_arguments)]
    pub fn start(
        ffmpeg_override: Option<&Path>,
        output_path: &Path,
        width: u32,
        height: u32,
        fps: u32,
        crf: u8,
        preset: &str,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        validate_video_settings(width, height, fps, crf, preset)?;
        if let Some(parent) = output_path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)?;
        }

        let ffmpeg = resolve_ffmpeg(ffmpeg_override);
        let temporary_path = temporary_output_path(output_path)?;
        if temporary_path.exists() {
            fs::remove_file(&temporary_path)?;
        }
        let mut child = Command::new(&ffmpeg)
            .args([
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgba",
                "-video_size",
                &format!("{width}x{height}"),
                "-framerate",
                &fps.to_string(),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                &crf.to_string(),
                "-pix_fmt",
                "yuv420p",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-colorspace",
                "bt709",
                "-color_range",
                "tv",
                "-x264-params",
                "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
                "-movflags",
                "+faststart",
                "-r",
                &fps.to_string(),
            ])
            .arg(&temporary_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| {
                format!(
                    "could not start FFmpeg at {:?}: {error}. Set --ffmpeg or FLUODDITY_FFMPEG to a working executable",
                    ffmpeg
                )
            })?;
        let stdin = child.stdin.take().ok_or("FFmpeg stdin was not available")?;
        let expected_frame_bytes = frame_byte_count(width, height)?;
        Ok(Self {
            child,
            stdin: Some(stdin),
            output_path: output_path.to_path_buf(),
            temporary_path,
            expected_frame_bytes,
            frame_count: 0,
            encoding_finished: false,
            published: false,
        })
    }

    pub fn write_rgba_frame(&mut self, frame: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
        if frame.len() != self.expected_frame_bytes {
            return Err(format!(
                "video frame has {} bytes; expected {} RGBA bytes",
                frame.len(),
                self.expected_frame_bytes
            )
            .into());
        }
        if self.encoding_finished {
            return Err("cannot write a frame after the video encoder has finished".into());
        }
        let stdin = self.stdin.as_mut().ok_or("FFmpeg stdin is closed")?;
        stdin.write_all(frame).map_err(|error| {
            format!(
                "could not send frame {} to FFmpeg: {error}",
                self.frame_count
            )
        })?;
        self.frame_count = self.frame_count.saturating_add(1);
        Ok(())
    }

    pub fn finish_encoding(&mut self) -> Result<u32, Box<dyn std::error::Error>> {
        if self.encoding_finished {
            return Ok(self.frame_count);
        }
        if self.frame_count == 0 {
            return Err("cannot publish a video with zero encoded frames".into());
        }
        if let Some(mut stdin) = self.stdin.take() {
            stdin.flush()?;
            drop(stdin);
        }
        let status = self.child.wait()?;
        self.encoding_finished = true;
        if !status.success() {
            return Err(format!("FFmpeg exited with status {status}").into());
        }
        let bytes = fs::metadata(&self.temporary_path)?.len();
        if bytes == 0 {
            return Err(format!(
                "FFmpeg reported success but wrote an empty file: {}",
                self.temporary_path.display()
            )
            .into());
        }
        Ok(self.frame_count)
    }

    pub fn staged_output_path(&self) -> &Path {
        &self.temporary_path
    }

    pub fn staged_output_bytes(&self) -> Result<u64, Box<dyn std::error::Error>> {
        if !self.encoding_finished {
            return Err("video encoding must finish before reading its staged size".into());
        }
        Ok(fs::metadata(&self.temporary_path)?.len())
    }

    pub fn mark_published(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        if !self.encoding_finished {
            return Err("video encoding must finish before publication".into());
        }
        if self.temporary_path.exists() {
            return Err(format!(
                "staged video still exists after publication: {}",
                self.temporary_path.display()
            )
            .into());
        }
        if fs::metadata(&self.output_path)?.len() == 0 {
            return Err(format!("published video is empty: {}", self.output_path.display()).into());
        }
        self.published = true;
        Ok(())
    }
}

impl Drop for FfmpegVideoRecorder {
    fn drop(&mut self) {
        if self.published {
            return;
        }
        if !self.encoding_finished {
            self.stdin.take();
            match self.child.try_wait() {
                Ok(Some(_)) => {}
                Ok(None) => {
                    let _ = self.child.kill();
                    let _ = self.child.wait();
                }
                Err(_) => {}
            }
        }
        let _ = fs::remove_file(&self.temporary_path);
    }
}

pub struct StagedArtifact {
    output_path: PathBuf,
    temporary_path: PathBuf,
}

impl StagedArtifact {
    pub fn new(output_path: &Path, role: &str) -> Result<Self, Box<dyn std::error::Error>> {
        if let Some(parent) = output_path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)?;
        }
        let temporary_path = sibling_work_path(output_path, role, "partial")?;
        match fs::symlink_metadata(&temporary_path) {
            Ok(_) => {
                return Err(format!(
                    "refusing to overwrite an existing staged artifact: {}",
                    temporary_path.display()
                )
                .into());
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(format!(
                    "could not inspect staged artifact path {}: {error}",
                    temporary_path.display()
                )
                .into());
            }
        }
        Ok(Self {
            output_path: output_path.to_path_buf(),
            temporary_path,
        })
    }

    pub fn output_path(&self) -> &Path {
        &self.output_path
    }

    pub fn temporary_path(&self) -> &Path {
        &self.temporary_path
    }
}

impl Drop for StagedArtifact {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.temporary_path);
    }
}

pub fn publish_staged_artifacts(
    artifacts: &[(&Path, &Path)],
) -> Result<(), Box<dyn std::error::Error>> {
    if artifacts.is_empty() {
        return Err("artifact publication requires at least one staged file".into());
    }

    let mut output_paths = std::collections::HashSet::new();
    for (staged_path, output_path) in artifacts {
        if staged_path == output_path {
            return Err("staged and final artifact paths must be distinct".into());
        }
        if !output_paths.insert((*output_path).to_path_buf()) {
            return Err(format!(
                "artifact publication has a duplicate output path: {}",
                output_path.display()
            )
            .into());
        }
        let metadata = fs::symlink_metadata(staged_path).map_err(|error| {
            format!(
                "staged artifact is unavailable at {}: {error}",
                staged_path.display()
            )
        })?;
        if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 {
            return Err(format!(
                "staged artifact must be a non-empty file: {}",
                staged_path.display()
            )
            .into());
        }
        if let Some(parent) = output_path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)?;
        }
        existing_regular_artifact(output_path)?;
    }

    let mut backups = Vec::new();
    for (_, output_path) in artifacts {
        let output_exists = match existing_regular_artifact(output_path) {
            Ok(exists) => exists,
            Err(error) => {
                let rollback_errors = restore_backups(&backups);
                return Err(publication_error(
                    format!(
                        "could not revalidate artifact output {}: {error}",
                        output_path.display()
                    ),
                    &rollback_errors,
                )
                .into());
            }
        };
        if !output_exists {
            continue;
        }
        let backup_path = sibling_work_path(output_path, "previous", "backup")?;
        if let Err(error) = fs::rename(output_path, &backup_path) {
            let rollback_errors = restore_backups(&backups);
            return Err(publication_error(
                format!(
                    "could not preserve existing artifact {}: {error}",
                    output_path.display()
                ),
                &rollback_errors,
            )
            .into());
        }
        backups.push(((*output_path).to_path_buf(), backup_path));
    }

    for (published_count, (staged_path, output_path)) in artifacts.iter().enumerate() {
        if let Err(error) = fs::rename(staged_path, output_path) {
            let mut rollback_errors = Vec::new();
            for (published_stage, published_output) in artifacts[..published_count].iter().rev() {
                if let Err(move_error) = fs::rename(published_output, published_stage)
                    && let Err(remove_error) = fs::remove_file(published_output)
                {
                    rollback_errors.push(format!(
                        "could not withdraw new artifact {} ({move_error}; {remove_error})",
                        published_output.display()
                    ));
                }
            }
            rollback_errors.extend(restore_backups(&backups));
            return Err(publication_error(
                format!(
                    "could not publish staged artifact {} to {}: {error}",
                    staged_path.display(),
                    output_path.display()
                ),
                &rollback_errors,
            )
            .into());
        }
    }

    for (_, backup_path) in backups {
        if let Err(error) = fs::remove_file(&backup_path) {
            eprintln!(
                "warning: published new artifact but could not remove backup {}: {error}",
                backup_path.display()
            );
        }
    }
    Ok(())
}

fn existing_regular_artifact(path: &Path) -> Result<bool, Box<dyn std::error::Error>> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(format!(
                    "existing artifact output must be a regular file, not a directory or symlink: {}",
                    path.display()
                )
                .into());
            }
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!(
            "could not inspect artifact output {}: {error}",
            path.display()
        )
        .into()),
    }
}

fn restore_backups(backups: &[(PathBuf, PathBuf)]) -> Vec<String> {
    let mut errors = Vec::new();
    for (output_path, backup_path) in backups.iter().rev() {
        if let Err(error) = fs::rename(backup_path, output_path) {
            errors.push(format!(
                "could not restore {} from {}: {error}",
                output_path.display(),
                backup_path.display()
            ));
        }
    }
    errors
}

fn publication_error(primary: String, rollback_errors: &[String]) -> String {
    if rollback_errors.is_empty() {
        primary
    } else {
        format!("{primary}; rollback errors: {}", rollback_errors.join("; "))
    }
}

fn sibling_work_path(
    output_path: &Path,
    role: &str,
    state: &str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let file_name = output_path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("artifact output path must have a UTF-8 file name")?;
    let extension = output_path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("bin");
    let sequence = ARTIFACT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let work_name = format!(
        ".{file_name}.{}.{}.{}.{}.{}",
        std::process::id(),
        sequence,
        role,
        state,
        extension
    );
    Ok(output_path.with_file_name(work_name))
}

pub fn validate_video_settings(
    width: u32,
    height: u32,
    fps: u32,
    crf: u8,
    preset: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    if width == 0 || height == 0 {
        return Err("video width and height must be greater than zero".into());
    }
    if !width.is_multiple_of(2) || !height.is_multiple_of(2) {
        return Err("H.264 yuv420p video width and height must both be even".into());
    }
    if !(1..=240).contains(&fps) {
        return Err("video FPS must be between 1 and 240".into());
    }
    if crf > 51 {
        return Err("video CRF must be between 0 and 51".into());
    }
    if !VALID_PRESETS.contains(&preset) {
        return Err(format!(
            "unsupported x264 preset {preset:?}; expected one of {}",
            VALID_PRESETS.join(", ")
        )
        .into());
    }
    frame_byte_count(width, height)?;
    Ok(())
}

fn frame_byte_count(width: u32, height: u32) -> Result<usize, Box<dyn std::error::Error>> {
    usize::try_from(u64::from(width) * u64::from(height) * 4)
        .map_err(|_| "video frame byte count exceeds this platform's address space".into())
}

fn temporary_output_path(output_path: &Path) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let file_name = output_path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("video output path must have a UTF-8 file name")?;
    let temporary_name = format!(".{file_name}.{}.partial.mp4", std::process::id());
    Ok(output_path.with_file_name(temporary_name))
}

fn resolve_ffmpeg(override_path: Option<&Path>) -> OsString {
    if let Some(path) = override_path {
        return path.as_os_str().to_owned();
    }
    if let Some(path) = env::var_os("FLUODDITY_FFMPEG")
        && !path.is_empty()
    {
        return path;
    }
    if let Ok(executable) = env::current_exe()
        && let Some(directory) = executable.parent()
    {
        for name in ["ffmpeg.exe", "ffmpeg"] {
            let candidate = directory.join(name);
            if candidate.is_file() {
                return candidate.into_os_string();
            }
        }
    }
    OsString::from("ffmpeg")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_directory(name: &str) -> PathBuf {
        let sequence = ARTIFACT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "fluoddity-video-export-{name}-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn accepts_uhd_sixty_fps_master_settings() {
        validate_video_settings(3840, 2160, 60, 15, "slow").unwrap();
        assert_eq!(frame_byte_count(3840, 2160).unwrap(), 33_177_600);
    }

    #[test]
    fn rejects_odd_h264_dimensions() {
        let error = validate_video_settings(1279, 720, 60, 15, "slow")
            .unwrap_err()
            .to_string();
        assert!(error.contains("must both be even"), "{error}");
    }

    #[test]
    fn rejects_unknown_encoder_preset() {
        let error = validate_video_settings(1920, 1080, 60, 15, "instant")
            .unwrap_err()
            .to_string();
        assert!(error.contains("unsupported x264 preset"), "{error}");
    }

    #[test]
    fn partial_output_keeps_an_mp4_extension() {
        let path = temporary_output_path(Path::new("Videos/master.mp4")).unwrap();
        let expected = format!(".master.mp4.{}.partial.mp4", std::process::id());
        assert_eq!(
            path.file_name().and_then(|name| name.to_str()),
            Some(expected.as_str())
        );
        assert_eq!(path.extension().and_then(|ext| ext.to_str()), Some("mp4"));
    }

    #[test]
    fn staged_publication_replaces_regular_files_as_one_transaction() {
        let directory = test_directory("publish");
        let video_output = directory.join("master.mp4");
        let report_output = directory.join("master.json");
        let video_stage = directory.join("video.partial.mp4");
        let report_stage = directory.join("report.partial.json");
        fs::write(&video_output, b"old-video").unwrap();
        fs::write(&report_output, b"old-report").unwrap();
        fs::write(&video_stage, b"new-video").unwrap();
        fs::write(&report_stage, b"new-report").unwrap();

        publish_staged_artifacts(&[
            (video_stage.as_path(), video_output.as_path()),
            (report_stage.as_path(), report_output.as_path()),
        ])
        .unwrap();

        assert_eq!(fs::read(&video_output).unwrap(), b"new-video");
        assert_eq!(fs::read(&report_output).unwrap(), b"new-report");
        assert!(!video_stage.exists());
        assert!(!report_stage.exists());
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn invalid_sidecar_target_preserves_every_existing_artifact() {
        let directory = test_directory("rollback");
        let video_output = directory.join("master.mp4");
        let poster_output = directory.join("blocked.ppm");
        let video_stage = directory.join("video.partial.mp4");
        let poster_stage = directory.join("poster.partial.ppm");
        fs::write(&video_output, b"known-good-video").unwrap();
        fs::create_dir(&poster_output).unwrap();
        fs::write(&video_stage, b"new-video").unwrap();
        fs::write(&poster_stage, b"new-poster").unwrap();

        let error = publish_staged_artifacts(&[
            (video_stage.as_path(), video_output.as_path()),
            (poster_stage.as_path(), poster_output.as_path()),
        ])
        .unwrap_err()
        .to_string();

        assert!(error.contains("regular file"), "{error}");
        assert_eq!(fs::read(&video_output).unwrap(), b"known-good-video");
        assert!(poster_output.is_dir());
        assert_eq!(fs::read(&video_stage).unwrap(), b"new-video");
        assert_eq!(fs::read(&poster_stage).unwrap(), b"new-poster");
        fs::remove_dir_all(directory).unwrap();
    }
}
