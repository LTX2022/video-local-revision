#!/usr/bin/env python3
"""Read-only technical video checks; matching metadata is not visual approval."""

import argparse
import json
import math
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import sys


class MediaError(Exception):
    pass


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def rational(value):
    try:
        value = Fraction(str(value))
        return f"{value.numerator}/{value.denominator}" if value > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def duration(stream):
    ticks = number(stream.get("duration_ts"))
    base = rational(stream.get("time_base"))
    if ticks is not None and base:
        return ticks * float(Fraction(base)), "stream.duration_ts*time_base"
    value = number(stream.get("duration"))
    if value is not None:
        return value, "stream.duration"
    # Container duration may include other streams, and is not video/audio duration.
    return None, "unknown"


def run(command, timeout):
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(command[0]).name} exceeded {timeout:g}s. "
                         "Retry with a larger --timeout if appropriate.") from exc
    except OSError as exc:
        raise MediaError(f"Could not run {command[0]}: {exc}") from exc


def diagnostic(text):
    return text.strip()[-4000:]


def inspect_media(filename, probe, decoder, timeout):
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise MediaError(f"Input is not a readable local file: {path}")
    proc = run([probe, "-v", "error", "-count_frames", "-show_streams",
                "-show_format", "-of", "json", str(path)], timeout)
    if proc.returncode:
        raise MediaError(f"ffprobe could not read {path}: "
                         f"{diagnostic(proc.stderr) or 'invalid or unsupported media'}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {path}") from exc
    video, audio = [], []
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind not in ("video", "audio"):
            continue
        if kind == "video" and stream.get("disposition", {}).get("attached_pic"):
            continue
        seconds, source = duration(stream)
        item = {"index": stream["index"], "codec": stream.get("codec_name"),
                "duration_seconds": seconds, "duration_source": source}
        if kind == "video":
            average = rational(stream.get("avg_frame_rate"))
            nominal = rational(stream.get("r_frame_rate"))
            raw_count = str(stream.get("nb_read_frames", ""))
            item.update(width=stream.get("width"), height=stream.get("height"),
                        average_fps=average, nominal_fps=nominal,
                        counted_frames=int(raw_count) if raw_count.isdigit() else None,
                        frame_count_source="ffprobe -count_frames: nb_read_frames",
                        cadence="unknown",
                        vfr_suspected=bool(average and nominal and average != nominal))
            video.append(item)
        else:
            item.update(sample_rate=number(stream.get("sample_rate")),
                        channels=stream.get("channels"))
            audio.append(item)
    if not video:
        raise MediaError(f"No playable video stream found in {path}; "
                         "choose a video file (cover artwork is excluded).")
    decoded = {"status": "not_requested"}
    if decoder:
        try:
            proc_decode = run([decoder, "-nostdin", "-v", "error", "-xerror",
                               "-i", str(path), "-map", "0:v?", "-map", "0:a?",
                               "-f", "null", "-"], timeout)
            errors = diagnostic(proc_decode.stderr)
            decoded = {"status": "failed" if proc_decode.returncode or errors else "passed",
                       "exit_code": proc_decode.returncode, "errors": errors,
                       "scope": "all video and audio streams; no output media written"}
        except MediaError as exc:
            decoded = {"status": "failed", "errors": str(exc)}
    fmt = data.get("format", {})
    return {"path": str(path), "size_bytes": path.stat().st_size,
            "format": fmt.get("format_name"),
            "container_duration_seconds": number(fmt.get("duration")),
            "video_streams": video, "audio_streams": audio,
            "probe_errors": diagnostic(proc.stderr), "decode": decoded}


def media_findings(media, label):
    findings = []
    if media["probe_errors"]:
        findings.append({"kind": "error", "property": f"{label}.probe",
                         "message": media["probe_errors"]})
    if media["decode"]["status"] == "failed":
        findings.append({"kind": "error", "property": f"{label}.decode",
                         "message": media["decode"]["errors"] or "Decoder exited with an error."})
    for i, video in enumerate(media["video_streams"]):
        if video["vfr_suspected"]:
            findings.append({"kind": "unknown", "property": f"{label}.video[{i}].cadence",
                             "message": "Average and nominal frame rates differ. VFR or "
                             "irregular timing is possible; cadence preservation is unverified."})
    return findings


def compare_media(source, result, targets=None):
    targets = targets or {}
    checks = []

    def check(prop, before, after, tolerance=None, *, target=None):
        expected = before if target is None else target
        match = None if expected is None or after is None else expected == after
        if tolerance is not None and match is not None:
            match = abs(expected - after) <= tolerance + 1e-9
        entry = {"property": prop, "expected": "same" if target is None else target, "source": before,
                 "result": after, "match": match}
        if tolerance is not None:
            entry["tolerance_seconds"] = tolerance
        checks.append(entry)

    for kind in ("video", "audio"):
        before_streams = source[f"{kind}_streams"]
        after_streams = result[f"{kind}_streams"]
        check(f"{kind}.stream_count", len(before_streams), len(after_streams))
        if not after_streams and any(key.startswith(f"{kind}.") for key in targets):
            check(f"{kind}.has_target_stream", bool(before_streams), False, target=True)
        for i, (before, after) in enumerate(zip(before_streams, after_streams)):
            prefix = f"{kind}[{i}]"
            properties = (("width", "height", "average_fps", "nominal_fps", "counted_frames")
                          if kind == "video" else ("sample_rate", "channels"))
            if f"{kind}.codec" in targets:
                properties += ("codec",)
            for prop in properties:
                check(f"{prefix}.{prop}", before[prop], after[prop],
                      target=targets.get(f"{kind}.{prop}"))
            if kind == "video":
                fps = before["average_fps"] or before["nominal_fps"]
                tolerance = 1 / float(Fraction(fps)) if fps else None
                if tolerance is None:
                    check(f"{prefix}.duration_seconds", None, None)
                    checks[-1]["note"] = "Unknown source FPS prevents one-frame tolerance."
                else:
                    check(f"{prefix}.duration_seconds", before["duration_seconds"],
                          after["duration_seconds"], tolerance)
                    checks[-1]["note"] = "Tolerance is one source metadata frame interval."
            else:
                rate = before["sample_rate"]
                tolerance = 1 / rate if rate else 1e-6
                check(f"{prefix}.duration_seconds", before["duration_seconds"],
                      after["duration_seconds"], tolerance)
                checks[-1]["note"] = "One source audio sample tolerance when sample rate is known."
    findings = media_findings(source, "source") + media_findings(result, "result")
    for item in checks:
        if item["match"] is not True:
            findings.append({"kind": "unknown" if item["match"] is None else "mismatch",
                             "property": item["property"],
                             "message": "Comparison unavailable." if item["match"] is None
                             else ("Differs from the requested target." if item["expected"] != "same"
                                   else "Differs from source; assess against requested export changes.")})
    if any(f["kind"] in ("error", "mismatch") for f in findings):
        match = False
    elif any(f["kind"] == "unknown" for f in findings):
        match = None
    else:
        match = True
    return {"operation": "compare",
            "comparison_basis": "source_with_targets" if targets else "expected_same",
            "source": source, "result": result, "comparisons": checks,
            "technical_match": match, "findings": findings}


def positive_seconds(value):
    parsed = number(value)
    if parsed is None or parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite positive number")
    return parsed


def positive_integer(value):
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return int(value)


def dimensions(value):
    width, separator, height = value.lower().partition("x")
    if not separator:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT")
    return positive_integer(width), positive_integer(height)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, files in (("inspect", ("input",)), ("compare", ("source", "result"))):
        sub = commands.add_parser(command)
        for name in files:
            sub.add_argument(name, help="local video file")
        sub.add_argument("--decode", action="store_true",
                         help="fully decode video/audio with ffmpeg; no output media is written")
        sub.add_argument("--timeout", type=positive_seconds, default=300,
                         help="maximum seconds per ffprobe/ffmpeg invocation (default: 300)")
        if command == "compare":
            sub.add_argument("--size", type=dimensions, help="target encoded video size (WIDTHxHEIGHT)")
            sub.add_argument("--video-codec", help="target ffprobe video codec name, e.g. h264")
            sub.add_argument("--audio-codec", help="target ffprobe audio codec name, e.g. aac")
            sub.add_argument("--audio-channels", type=positive_integer, help="target channels per audio stream")
            sub.add_argument("--audio-sample-rate", type=positive_integer, help="target sample rate in Hz")
    args = parser.parse_args()
    limitations = [
        "Technical matches do not establish visual correctness or satisfy creative acceptance.",
        "Frame-rate metadata and frame counts do not verify timestamp cadence or frame content.",
        "Matching audio counts/durations do not verify audio content, sync, or loudness.",
        "Streams are paired by video/audio order; container duration is not substituted for stream duration.",
        "Expected-same mismatches may be intentional export changes and are findings, not task failure.",
    ]
    try:
        probe = shutil.which("ffprobe")
        decoder = shutil.which("ffmpeg") if args.decode else None
        if not probe:
            raise MediaError("ffprobe is required but was not found. Make an existing ffprobe "
                             "installation available on PATH, then retry.")
        if args.decode and not decoder:
            raise MediaError("--decode requires ffmpeg on PATH; provide it or omit --decode.")
        if args.command == "inspect":
            media = inspect_media(args.input, probe, decoder, args.timeout)
            findings = media_findings(media, "input")
            report = {"operation": "inspect", "media": media, "findings": findings,
                      "technical_match": False if any(f["kind"] == "error" for f in findings) else None}
        else:
            source = inspect_media(args.source, probe, decoder, args.timeout)
            result = inspect_media(args.result, probe, decoder, args.timeout)
            targets = {}
            if args.size:
                targets.update(zip(("video.width", "video.height"), args.size))
            for key, value in (("video.codec", args.video_codec), ("audio.codec", args.audio_codec),
                               ("audio.channels", args.audio_channels),
                               ("audio.sample_rate", args.audio_sample_rate)):
                if value is not None:
                    targets[key] = value
            report = compare_media(source, result, targets)
        exit_code = 1 if any(f["kind"] == "error" for f in report["findings"]) else 0
    except (MediaError, OSError) as exc:
        report = {"operation": args.command, "technical_match": False,
                  "error": str(exc), "findings": [{"kind": "error", "message": str(exc)}]}
        exit_code = 2
    report.update(visual_review="required", audio_content_review="not_performed",
                  cadence_preservation="not_verified", limitations=limitations)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
