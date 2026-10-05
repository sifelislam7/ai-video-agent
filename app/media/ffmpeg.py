"""Thin wrapper around FFmpeg.

Uses the static binary shipped by ``imageio-ffmpeg`` so no system install is
required, but prefers a system ``ffmpeg`` when one is on PATH.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)")


class FFmpegError(RuntimeError):
    pass


@lru_cache
def ffmpeg_exe() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise FFmpegError(
            "FFmpeg not found. Install it system-wide or `pip install imageio-ffmpeg`."
        ) from exc


def run(args: list[str], *, timeout: int = 900) -> str:
    """Run ffmpeg with the given arguments; returns combined stderr output."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg %s", " ".join(cmd[1:]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg failed ({proc.returncode}): {proc.stderr.strip()[-1500:]}"
        )
    return proc.stderr


def probe_duration(path: str | Path) -> float:
    """Return media duration in seconds (0.0 when unknown)."""
    path = Path(path)
    if not path.exists():
        return 0.0
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            out = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "json", str(path),
                ],
                capture_output=True, text=True, timeout=60,
            )
            return float(json.loads(out.stdout)["format"]["duration"])
        except Exception:
            pass
    # Fall back to parsing `ffmpeg -i` output.
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    match = _DURATION_RE.search(proc.stderr)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# --------------------------------------------------------------------- audio
def make_silence(duration: float, out_path: str | Path, sample_rate: int = 44100) -> Path:
    out_path = Path(out_path)
    run([
        "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=stereo",
        "-t", f"{max(duration, 0.1):.3f}", "-c:a", "pcm_s16le", str(out_path),
    ])
    return out_path


# Simple diatonic pads, one per mood. Frequencies in Hz (root, third, fifth).
_MOOD_CHORDS: dict[str, list[tuple[float, float, float]]] = {
    "upbeat":     [(261.63, 329.63, 392.00), (349.23, 440.00, 523.25),
                   (392.00, 493.88, 587.33), (329.63, 392.00, 493.88)],
    "calm":       [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63),
                   (196.00, 246.94, 293.66), (164.81, 196.00, 246.94)],
    "epic":       [(146.83, 174.61, 220.00), (196.00, 233.08, 293.66),
                   (174.61, 207.65, 261.63), (130.81, 155.56, 196.00)],
    "mysterious": [(146.83, 174.61, 207.65), (155.56, 185.00, 233.08),
                   (130.81, 155.56, 196.00), (174.61, 207.65, 261.63)],
}


def make_ambient_bed(duration: float, out_path: str | Path, mood: str = "upbeat") -> Path:
    """Synthesize a soft royalty-free chord pad with FFmpeg (fully offline).

    Four chords loop for the requested duration — intentionally quiet and simple,
    it is meant as a bed under narration, not as a finished soundtrack.
    """
    out_path = Path(out_path)
    chords = _MOOD_CHORDS.get(mood.lower(), _MOOD_CHORDS["upbeat"])
    bar = max(2.0, min(4.0, duration / 4))
    inputs: list[str] = []
    labels: list[str] = []
    idx = 0
    for chord in chords:
        for freq in chord:
            inputs += ["-f", "lavfi", "-i", f"sine=frequency={freq:.2f}:duration={bar:.3f}"]
            labels.append(f"[{idx}:a]")
            idx += 1
    per_chord = len(chords[0])
    mixes = []
    for c in range(len(chords)):
        group = "".join(labels[c * per_chord:(c + 1) * per_chord])
        mixes.append(
            f"{group}amix=inputs={per_chord}:normalize=1,"
            f"afade=t=in:st=0:d={bar / 2:.2f},afade=t=out:st={bar / 2:.2f}:d={bar / 2:.2f}[c{c}]"
        )
    concat_in = "".join(f"[c{c}]" for c in range(len(chords)))
    filter_complex = (
        ";".join(mixes)
        + f";{concat_in}concat=n={len(chords)}:v=0:a=1[seq]"
        + ";[seq]aloop=loop=-1:size=2e+09[loop]"
        + f";[loop]atrim=0:{duration:.3f},lowpass=f=900,tremolo=f=0.4:d=0.25,"
          f"aecho=0.8:0.85:120:0.25,volume=0.5,"
          f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(0.0, duration - 1.5):.3f}:d=1.5[out]"
    )
    run([
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(out_path),
    ])
    return out_path


def concat_audio(
    segments: list[tuple[str | Path, float]], out_path: str | Path
) -> Path:
    """Concatenate audio files, padding/trimming each to its target duration."""
    out_path = Path(out_path)
    if not segments:
        return make_silence(1.0, out_path)
    inputs: list[str] = []
    filters: list[str] = []
    for i, (path, dur) in enumerate(segments):
        inputs += ["-i", str(path)]
        filters.append(
            f"[{i}:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"apad,atrim=0:{max(dur, 0.1):.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
    joined = "".join(f"[a{i}]" for i in range(len(segments)))
    filter_complex = ";".join(filters) + f";{joined}concat=n={len(segments)}:v=0:a=1[out]"
    run([*inputs, "-filter_complex", filter_complex, "-map", "[out]",
         "-c:a", "pcm_s16le", str(out_path)])
    return out_path


def mix_audio(
    voice: str | Path | None,
    music: str | Path | None,
    out_path: str | Path,
    duration: float,
    music_volume: float = 0.18,
) -> Path:
    """Mix a voice track with a (quieter) music bed."""
    out_path = Path(out_path)
    if voice and not music:
        run(["-i", str(voice), "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(out_path)])
        return out_path
    if music and not voice:
        run(["-i", str(music), "-filter:a", f"volume={music_volume * 2:.2f}",
             "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(out_path)])
        return out_path
    if not voice and not music:
        return make_silence(duration, out_path)
    filter_complex = (
        f"[0:a]aresample=44100,apad,atrim=0:{duration:.3f}[v];"
        f"[1:a]aresample=44100,volume={music_volume:.3f},apad,atrim=0:{duration:.3f}[m];"
        "[v][m]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[out]"
    )
    run(["-i", str(voice), "-i", str(music), "-filter_complex", filter_complex,
         "-map", "[out]", "-c:a", "pcm_s16le", str(out_path)])
    return out_path


# --------------------------------------------------------------------- video
def still_to_clip(
    image: str | Path,
    out_path: str | Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    *,
    zoom_in: bool = True,
    fade: float = 0.35,
) -> Path:
    """Turn a still image into a Ken-Burns style clip (video only)."""
    out_path = Path(out_path)
    duration = max(duration, 0.5)
    frames = max(int(round(duration * fps)), 1)
    # Up-scale first: zoompan is much smoother on a large source.
    big_w, big_h = width * 2, height * 2
    zexpr = (
        f"min(zoom+{0.12 / frames:.6f},1.12)" if zoom_in
        else f"if(lte(zoom,1.0),1.12,max(zoom-{0.12 / frames:.6f},1.0))"
    )
    fade_out_start = max(duration - fade, 0.0)
    vf = (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
        f"crop={big_w}:{big_h},"
        f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={width}x{height}:fps={fps},"
        f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={fade_out_start:.2f}:d={fade:.2f},"
        "format=yuv420p"
    )
    run([
        "-loop", "1", "-i", str(image), "-t", f"{duration:.3f}", "-vf", vf,
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out_path),
    ])
    return out_path


def concat_clips(clips: list[str | Path], out_path: str | Path, workdir: Path) -> Path:
    out_path = Path(out_path)
    if len(clips) == 1:
        shutil.copyfile(clips[0], out_path)
        return out_path
    list_file = workdir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{Path(c).resolve().as_posix()}'" for c in clips), encoding="utf-8"
    )
    run(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)])
    return out_path


def mux(video: str | Path, audio: str | Path | None, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    args = ["-i", str(video)]
    if audio:
        args += ["-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                 "-shortest", "-movflags", "+faststart"]
    else:
        args += ["-c:v", "copy", "-movflags", "+faststart"]
    run([*args, str(out_path)])
    return out_path


def extract_thumbnail(video: str | Path, out_path: str | Path, at: float = 1.0) -> Path:
    out_path = Path(out_path)
    run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out_path)])
    return out_path
