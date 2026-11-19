#!/usr/bin/env python3
"""Extract a synchronized, silent side-by-side review and a native-size crop pair."""

import argparse
from bisect import bisect_left
from fractions import Fraction
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

sys.dont_write_bytecode = True
from media_check import MediaError, positive_seconds, run


def seconds(value):
    try:
        time = Fraction(value)
        if time >= 0:
            return time
    except (ValueError, ZeroDivisionError):
        pass
    raise argparse.ArgumentTypeError("expected non-negative seconds")


def rectangle(value):
    try:
        x, y, width, height = (int(field) for field in value.split(","))
        if min(x, y) >= 0 and min(width, height) >= 1:
            return x, y, width, height
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected X,Y,WIDTH,HEIGHT in decoded pixels")


def checked_run(command, timeout):
    process = run(command, timeout)
    if process.returncode or process.stderr.strip():
        raise MediaError(process.stderr.strip()[-2400:] or f"{command[0]} failed")
    return process.stdout


def read_timeline(probe, path, timeout):
    data = json.loads(checked_run([probe, "-v", "error", "-select_streams", "V:0",
                                   "-show_frames", "-show_streams",
                                   "-show_entries", "frame=best_effort_timestamp:stream=index,width,height,time_base",
                                   "-of", "json", str(path)], timeout))
    try:
        stream = data["streams"][0]
        ticks = [int(f["best_effort_timestamp"]) for f in data["frames"]]
        multiplier = Fraction(stream["time_base"])
        timestamps = [(tick - ticks[0]) * multiplier for tick in ticks]
        if not timestamps or any(a >= b for a, b in zip(timestamps, timestamps[1:])):
            raise ValueError
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise MediaError(f"Missing or non-increasing video timestamps in {path}") from exc
    return stream["index"], (stream["width"], stream["height"]), timestamps


def export_pair(ffmpeg, left, right, streams, span, crop, mode, output, timeout):
    first, last = span
    x, y, width, height = crop
    pixel_format = ",format=rgb24" if mode == "png" else ""
    graph = ";".join(
        f"[{i}:{stream}]trim=start_frame={first}:end_frame={last},"
        f"setpts=PTS-STARTPTS,settb=1/1000000,"
        f"crop=w={width}:h={height}:x={x}:y={y}:exact=1{pixel_format}[{side}]"
        for i, (stream, side) in enumerate(zip(streams, ("left", "right"))))
    graph += ";[left][right]hstack=inputs=2:shortest=1"
    if mode == "png":
        options = ["-frames:v", "1", "-update", "1"]
    else:
        graph += ",pad=iw:ceil(ih/2)*2"
        options = ["-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                   "-fps_mode", "passthrough", "-enc_time_base", "1:1000000",
                   "-video_track_timescale", "1000000", "-movflags", "+faststart"]
    checked_run([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-n",
                 "-noautorotate", "-i", str(left), "-noautorotate", "-i", str(right),
                 "-filter_complex", graph + "[pair]", "-map", "[pair]",
                 "-an", *options, str(output)], timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--start", type=seconds, required=True, help="inclusive seconds from first video frame")
    parser.add_argument("--end", type=seconds, required=True, help="exclusive seconds from first video frame")
    parser.add_argument("--roi", type=rectangle, help="X,Y,WIDTH,HEIGHT, default full decoded frame")
    parser.add_argument("--frame", type=int, help="absolute zero-based input frame for PNG, default first in range")
    parser.add_argument("--out", type=Path, required=True, help="new output directory with an existing parent")
    parser.add_argument("--timeout", type=positive_seconds, default=120)
    args = parser.parse_args()
    try:
        left, right = (path.expanduser().resolve(strict=True) for path in (args.left, args.right))
        out = args.out.expanduser().absolute()
        probe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
        if not probe or not ffmpeg:
            raise MediaError("ffprobe and ffmpeg with libx264 are required")
        if not left.is_file() or not right.is_file():
            raise MediaError("both inputs must be local files")
        if out.exists() or out.is_symlink():
            raise MediaError("choose a new output directory")
        if args.end <= args.start:
            raise MediaError("--end must be greater than --start")
        left_stream, size, left_times = read_timeline(probe, left, args.timeout)
        right_stream, right_size, right_times = read_timeline(probe, right, args.timeout)
        if size != right_size:
            raise MediaError("decoded dimensions differ. Compare two exports at the same size")
        start, end = (bisect_left(left_times, time) for time in (args.start, args.end))
        right_span = tuple(bisect_left(right_times, time) for time in (args.start, args.end))
        if start >= end:
            raise MediaError("requested range contains no frames")
        if right_span != (start, end) or left_times[start:end] != right_times[start:end]:
            raise MediaError("frame ordinals or timestamps differ in the selected range. Use aligned exports")
        frame = start if args.frame is None else args.frame
        if not start <= frame < end:
            raise MediaError("--frame must be inside the selected range")
        crop = args.roi or (0, 0, *size)
        x, y, width, height = crop
        if x + width > size[0] or y + height > size[1]:
            raise MediaError("--roi extends outside the decoded frame")

        with TemporaryDirectory(prefix=".compare-", dir=out.parent) as staging:
            tmp = Path(staging)
            video = tmp / "review.mp4"
            still = tmp / "frame.png"
            streams = left_stream, right_stream
            export_pair(ffmpeg, left, right, streams, (start, end), crop, "mp4", video, args.timeout)
            export_pair(ffmpeg, left, right, streams, (frame, frame + 1), crop, "png", still, args.timeout)
            _, _, timeline = read_timeline(probe, video, args.timeout)
            expected = [t - left_times[start] for t in left_times[start:end]]
            tolerance = Fraction(1, 1000000)
            if len(timeline) != len(expected) or any(abs(actual - target) > tolerance
                                                     for actual, target in zip(timeline, expected)):
                raise MediaError("export did not preserve selected frame timing")
            mapping = tmp / "frames.tsv"
            with mapping.open("w", encoding="utf-8") as file:
                file.write("review_frame\tinput_frame\tsource_seconds\tis_still\n")
                for index, time in enumerate(left_times[start:end], start=start):
                    file.write(f"{index-start}\t{index}\t{float(time):.9f}\t{int(index == frame)}\n")
            out.mkdir()
            for path in (video, still, mapping):
                path.replace(out / path.name)
    except (MediaError, OSError, ValueError) as exc:
        parser.exit(2, f"compare_region: {exc}\n")
    print(f"{end-start} frames aligned. PNG shows input frame {frame}. Output: {out}")


if __name__ == "__main__":
    main()
