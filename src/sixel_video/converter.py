#!/usr/bin/env python3
"""Convert an MP4 to compressed, one-frame-per-line sixel animation."""

import argparse
import bz2
import ctypes
import ctypes.util
import math
import os
from pathlib import Path
import re
import sys
import time


class SixelEncoder:
    def __init__(self, library, colors, palette_mode="frame", scene_threshold=35):
        self.lib = ctypes.CDLL(library or ctypes.util.find_library("sixel") or "libsixel.so.1")
        self.write_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
        signatures = {
            "sixel_output_new": ([ctypes.POINTER(ctypes.c_void_p), self.write_type, ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
            "sixel_dither_new": ([ctypes.POINTER(ctypes.c_void_p), ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
            "sixel_dither_initialize": ([ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 6, ctypes.c_int),
            "sixel_encode": ([ctypes.c_void_p] + [ctypes.c_int] * 3 + [ctypes.c_void_p] * 2, ctypes.c_int),
            "sixel_output_set_palette_type": ([ctypes.c_void_p, ctypes.c_int], None),
            "sixel_output_set_encode_policy": ([ctypes.c_void_p, ctypes.c_int], None),
            "sixel_dither_set_diffusion_type": ([ctypes.c_void_p, ctypes.c_int], None),
            "sixel_dither_set_palette": ([ctypes.c_void_p, ctypes.c_void_p], None),
            "sixel_dither_set_pixelformat": ([ctypes.c_void_p, ctypes.c_int], None),
            "sixel_dither_get_palette": ([ctypes.c_void_p], ctypes.c_void_p),
            "sixel_dither_get_num_of_palette_colors": ([ctypes.c_void_p], ctypes.c_int),
            "sixel_output_unref": ([ctypes.c_void_p], None),
            "sixel_dither_unref": ([ctypes.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes = arguments
            function.restype = result
        self.chunks = []
        self.callback = self.write_type(self.write)
        self.output = ctypes.c_void_p()
        self.dither = ctypes.c_void_p()
        self.colors = colors
        self.palette_mode = palette_mode
        self.scene_threshold = scene_threshold
        self.palette = None
        self.palette_source = None
        self.check(self.lib.sixel_output_new(ctypes.byref(self.output), self.callback, None, None))
        self.lib.sixel_output_set_palette_type(self.output, 2)  # RGB percentages.
        self.lib.sixel_output_set_encode_policy(self.output, 2)  # Smallest output.

    @staticmethod
    def check(status):
        if status & 0x1000:
            raise RuntimeError("libsixel failed with status {:#x}".format(status))

    def write(self, data, size, private):
        self.chunks.append(ctypes.string_at(data, size))
        return size

    def frame(self):
        return b"\x1b[H" + b"".join(self.chunks).replace(b"\n", b"").replace(b"\r", b"") + b"\n"

    def encode(self, rgb):
        height, width, channels = rgb.shape
        assert channels == 3 and rgb.flags.c_contiguous
        pixels = ctypes.c_void_p(rgb.ctypes.data)
        refresh = self.palette_mode == "frame" or self.palette is None
        if not refresh:
            import numpy as np

            refresh = (self.palette_source.shape != rgb.shape
                       or np.abs(rgb.astype(np.int16) - self.palette_source.astype(np.int16)).mean() >= self.scene_threshold)
        # Initialization replaces the palette without invalidating libsixel's
        # RGB-to-index cache. Each frame needs a fresh context for its palette.
        colors = self.colors if refresh else len(self.palette)
        self.check(self.lib.sixel_dither_new(ctypes.byref(self.dither), colors, None))
        try:
            if refresh:
                self.check(self.lib.sixel_dither_initialize(self.dither, pixels, width, height, 3, 0, 0, 1))
                if self.palette_mode != "frame":
                    import numpy as np

                    count = self.lib.sixel_dither_get_num_of_palette_colors(self.dither)
                    palette = self.lib.sixel_dither_get_palette(self.dither)
                    self.palette = np.zeros((max(2, count), 3), dtype=np.uint8)
                    self.palette[:count] = np.frombuffer(ctypes.string_at(palette, count * 3), dtype=np.uint8).reshape(count, 3)
                    self.palette_source = rgb.copy()
            else:
                self.lib.sixel_dither_set_palette(self.dither, ctypes.c_void_p(self.palette.ctypes.data))
                self.lib.sixel_dither_set_pixelformat(self.dither, 3)  # RGB888.
            self.lib.sixel_dither_set_diffusion_type(self.dither, 1)  # Avoid dither noise.
            self.chunks.clear()
            self.check(self.lib.sixel_encode(pixels, width, height, 3, self.dither, self.output))
            return self.frame()
        finally:
            self.lib.sixel_dither_unref(self.dither)
            self.dither = ctypes.c_void_p()

    def encode_indexed(self, indices, palette):
        """Encode a patch; index 255 is outside its palette and stays unpainted."""
        height, width = indices.shape
        assert 2 <= len(palette) <= 255 and indices.flags.c_contiguous
        dither = ctypes.c_void_p()
        self.check(self.lib.sixel_dither_new(ctypes.byref(dither), len(palette), None))
        try:
            self.lib.sixel_dither_set_palette(dither, ctypes.c_void_p(palette.ctypes.data))
            self.lib.sixel_dither_set_pixelformat(dither, 0x83)  # PAL8.
            self.chunks.clear()
            self.check(self.lib.sixel_encode(ctypes.c_void_p(indices.ctypes.data), width, height, 1, dither, self.output))
            return self.frame()
        finally:
            self.lib.sixel_dither_unref(dither)

    def close(self):
        if self.dither:
            self.lib.sixel_dither_unref(self.dither)
            self.dither = ctypes.c_void_p()
        if self.output:
            self.lib.sixel_output_unref(self.output)
            self.output = ctypes.c_void_p()


class DeltaEncoder:
    """Omit redundant painting, with optional bounded color error."""

    def __init__(self, encoder, keyframe_frames, optimize="raw", accelerator="auto", threshold=0, region="sparse"):
        import numpy as np

        self.np = np
        self.accelerator = "numpy"
        self.compare = self.changed_pixels
        if accelerator != "numpy":
            try:
                from sixel_video._delta import changed_mask
            except ImportError:
                if accelerator == "cython":
                    raise RuntimeError("Cython accelerator unavailable; install sixel-video with SIXEL_VIDEO_BUILD_CYTHON=1")
            else:
                self.compare = changed_mask
                self.accelerator = "cython"
        self.encoder = encoder
        self.lib = encoder.lib
        signatures = {
            "sixel_allocator_new": ([ctypes.POINTER(ctypes.c_void_p)] + [ctypes.c_void_p] * 4, ctypes.c_int),
            "sixel_allocator_unref": ([ctypes.c_void_p], None),
            "sixel_allocator_free": ([ctypes.c_void_p, ctypes.c_void_p], None),
            "sixel_decode_raw": ([ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
                                 + [ctypes.POINTER(ctypes.c_int)] * 2
                                 + [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int), ctypes.c_void_p], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes = arguments
            function.restype = result
        self.allocator = ctypes.c_void_p()
        encoder.check(self.lib.sixel_allocator_new(ctypes.byref(self.allocator), None, None, None, None))
        self.keyframe_frames = keyframe_frames
        self.optimize = optimize
        self.threshold = threshold
        self.region = region
        self.previous = None
        self.frames = self.keyframes = self.delta_frames = 0
        self.last_keyframe = 0
        self.full_bytes = self.output_bytes = 0

    @staticmethod
    def transparent(frame):
        # Mark every frame, including complete keyframes, so the player knows
        # from the start that it must retain this stream's dependent updates.
        start = frame.index(b"\x1bP")
        end = frame.index(b"q", start)
        return frame[:start] + b"\x1bP0;1;0q" + frame[end + 1:]

    @staticmethod
    def changed_pixels(current, previous, threshold=0):
        # Three vectorized comparisons avoid NumPy's per-pixel axis reduction.
        if threshold:
            import numpy as np

            difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
            return ((difference[:, :, 0] > threshold) | (difference[:, :, 1] > threshold)
                    | (difference[:, :, 2] > threshold))
        return ((current[:, :, 0] != previous[:, :, 0])
                | (current[:, :, 1] != previous[:, :, 1])
                | (current[:, :, 2] != previous[:, :, 2]))

    def decode(self, frame, shape):
        """Recover the actual palette colors selected by full-frame encoding."""
        np = self.np
        pixels, palette = ctypes.c_void_p(), ctypes.c_void_p()
        width, height, colors = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        data = frame[frame.index(b"\x1bP"):]
        try:
            self.encoder.check(self.lib.sixel_decode_raw(data, len(data), ctypes.byref(pixels),
                                                       ctypes.byref(width), ctypes.byref(height),
                                                       ctypes.byref(palette), ctypes.byref(colors), self.allocator))
            if (height.value, width.value) != shape or not 1 <= colors.value <= 256:
                raise RuntimeError("libsixel decoded unexpected dimensions or palette size")
            indices = np.frombuffer(ctypes.string_at(pixels, width.value * height.value), dtype=np.uint8).reshape(shape)
            rgb_palette = np.frombuffer(ctypes.string_at(palette, colors.value * 3), dtype=np.uint8).reshape(-1, 3)
            return indices, rgb_palette
        finally:
            self.lib.sixel_allocator_free(self.allocator, pixels)
            self.lib.sixel_allocator_free(self.allocator, palette)

    def patch(self, indices, palette, painted):
        np = self.np
        colors = np.unique(indices[painted])
        if len(colors) >= 256:
            return None
        # Index 255 outside the patch palette leaves those pixels unpainted.
        mapping = np.full(256, 255, dtype=np.uint8)
        mapping[colors] = np.arange(len(colors), dtype=np.uint8)
        patch = np.where(painted, mapping[indices], 255).astype(np.uint8)
        patch_palette = np.zeros((max(2, len(colors)), 3), dtype=np.uint8)
        patch_palette[:len(colors)] = palette[colors]
        return self.transparent(self.encoder.encode_indexed(patch, patch_palette))

    def cost(self, data):
        # Final compression also finds patterns across neighboring frames;
        # independently compressed frame sizes are a selection heuristic.
        return len(bz2.compress(data, compresslevel=9)) if self.optimize == "compressed" else len(data)

    def encode(self, rgb):
        np = self.np
        full = self.encoder.encode(rgb)
        indices, palette = self.decode(full, rgb.shape[:2])
        # Compare displayed RGB percentages, not indices from changing palettes.
        percentages = ((palette.astype(np.uint16) * 100 + 127) // 255).astype(np.uint8)
        displayed = percentages[indices]
        data = self.transparent(full)
        keyframe = (self.previous is None or self.previous.shape != displayed.shape
                    or self.frames - self.last_keyframe >= self.keyframe_frames)
        painted = None
        if not keyframe:
            changed = self.compare(displayed, self.previous, self.threshold)
            if not changed.any():
                height, width = indices.shape
                data = b'\x1b[H\x1bP0;1;0q"1;1;' + str(width).encode() + b';' + str(height).encode() + b'\x1b\\\n'
                painted = changed
            else:
                regions = [changed] if self.region != "rectangle" else []
                if self.region != "sparse":
                    ys, xs = np.nonzero(changed)
                    rectangle = np.zeros_like(changed)
                    rectangle[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
                    if self.region == "rectangle" or not np.array_equal(rectangle, changed):
                        regions.append(rectangle)
                best_cost = self.cost(data)
                for region in regions:
                    candidate = self.patch(indices, palette, region)
                    if candidate is not None:
                        cost = self.cost(candidate)
                        if cost < best_cost:
                            data, painted, best_cost = candidate, region, cost
                keyframe = painted is None
        if keyframe:
            self.last_keyframe = self.frames
            self.keyframes += 1
        else:
            self.delta_frames += 1
        # Track the pixels actually displayed, including unchanged pixels that
        # a selected rectangle repaints. Small skipped changes must accumulate
        # against this reconstruction, never against the previous source frame.
        if self.threshold and not keyframe:
            self.previous = np.where(painted[:, :, None], displayed, self.previous).astype(np.uint8)
        else:
            self.previous = displayed
        self.frames += 1
        self.full_bytes += len(full)
        self.output_bytes += len(data)
        return data

    def close(self):
        if self.allocator:
            self.lib.sixel_allocator_unref(self.allocator)
            self.allocator = ctypes.c_void_p()


class TemporalDenoiser:
    """Smooth small RGB fluctuations while retaining larger changes immediately."""

    def __init__(self, strength=0, threshold=12):
        self.strength = strength
        self.threshold = threshold
        self.previous = None

    def process(self, rgb):
        import numpy as np

        if self.strength and self.previous is not None and self.previous.shape == rgb.shape:
            difference = np.abs(rgb.astype(np.int16) - self.previous.astype(np.int16))
            quiet = ((difference[:, :, 0] <= self.threshold) & (difference[:, :, 1] <= self.threshold)
                     & (difference[:, :, 2] <= self.threshold))
            smooth = np.floor(rgb.astype(np.float32) * (1 - self.strength)
                              + self.previous.astype(np.float32) * self.strength + 0.5).astype(np.uint8)
            rgb = np.where(quiet[:, :, None], smooth, rgb).astype(np.uint8)
        if self.strength:
            self.previous = rgb.copy()
        return rgb


def supports_sixel(stream, timeout=0.35):
    """Probe the terminal attached to the progress output; restore its input mode."""
    if not stream.isatty():
        return False
    try:
        import select
        import termios
        import tty
    except ImportError:
        return False
    fd = None
    original = None
    try:
        fd = os.open(os.ttyname(stream.fileno()), os.O_RDWR | os.O_NOCTTY)
        # Leave already-pending user input untouched.
        if select.select([fd], [], [], 0)[0]:
            return False
        original = termios.tcgetattr(fd)
        tty.setcbreak(fd, termios.TCSANOW)
        current = termios.tcgetattr(fd)
        current[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, current)
        os.write(fd, b"\x1b[c")
        deadline = time.monotonic() + timeout
        response = bytearray()
        while len(response) < 256:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                return False
            data = os.read(fd, 1)
            if not data:
                return False
            response.extend(data)
            match = re.search(rb"(?:\x1b\[|\x9b)\?([0-9;]+)c", response)
            if match:
                return b"4" in match[1].split(b";")
        return False
    except (OSError, ValueError, termios.error):
        return False
    finally:
        if original is not None:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        if fd is not None:
            os.close(fd)


def duration(seconds):
    if seconds is None:
        return "--:--"
    seconds = max(0, math.ceil(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, seconds) if hours else "{:02d}:{:02d}".format(minutes, seconds)


class ConversionProgress:
    """Show conversion progress on stderr, with optional sixel artwork."""

    def __init__(self, total, library=None, style="auto", stream=None):
        self.stream = stream if stream is not None else sys.stderr
        self.total = total
        self.start = time.monotonic()
        self.last_update = -math.inf
        self.tty = self.stream.isatty()
        self.graphic = None
        self.reserved = False
        self.closed = False
        if style != "text" and supports_sixel(self.stream):
            try:
                self.graphic = SixelEncoder(library, 4)
            except (OSError, RuntimeError):
                pass

    def columns(self):
        try:
            return os.get_terminal_size(self.stream.fileno()).columns
        except (OSError, ValueError, AttributeError):
            return 80

    def update(self, count, force=False, stage=""):
        now = time.monotonic()
        if not force and now - self.last_update < (0.2 if self.tty else 1.0):
            return
        self.last_update = now
        elapsed = now - self.start
        speed = count / elapsed if elapsed else 0
        fraction = min(1.0, count / self.total) if self.total else 0
        eta = max(0, self.total - count) / speed if speed else None
        status = "{:5.1f}% {}/{} ETA {} {:5.1f} fps".format(
            fraction * 100, count, self.total, duration(eta), speed)
        if stage:
            status += " | " + stage
        columns = self.columns()
        if self.graphic is not None:
            import numpy as np

            width = min(320, max(32, (columns - 2) * 4))
            rgb = np.empty((12, width, 3), dtype=np.uint8)
            rgb[:] = (28, 35, 45)
            rgb[2:10, 2:width - 2] = (65, 76, 90)
            filled = round((width - 4) * fraction)
            rgb[2:10, 2:2 + filled] = (45, 195, 150)
            image = self.graphic.encode(rgb)[3:-1]  # Remove frame home and newline.
            if not self.reserved:
                self.stream.write("\n\n\n\x1b[3F")
                self.reserved = True
            self.stream.write("\x1b7\r\x1b[2K" + status[:max(1, columns - 1)] + "\r\n" + image.decode("ascii") + "\x1b8")
        else:
            width = max(4, min(30, columns - len(status) - 4))
            filled = round(width * fraction)
            text = "[{}{}] {}".format("=" * filled, "-" * (width - filled), status)
            if self.tty:
                self.stream.write("\r\x1b[2K" + text[:max(1, columns - 1)])
            else:
                self.stream.write(text + "\n")
        self.stream.flush()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.graphic is not None:
            self.graphic.close()
        if self.reserved:
            self.stream.write("\x1b[3E")
        elif self.tty:
            self.stream.write("\n")
        self.stream.flush()


class SplitOutput:
    """Split a compressed stream without changing its bytes."""

    def __init__(self, path, limit):
        self.path = path
        self.limit = limit
        self.parts = []
        self.file = None
        self.size = 0

    def write(self, data):
        while data:
            if self.file is None:
                part = self.path.with_name(self.path.name + ".part{:03d}".format(len(self.parts)))
                self.parts.append(part.name)
                self.file = part.open("wb")
                self.size = 0
            amount = min(len(data), self.limit - self.size)
            self.file.write(data[:amount])
            self.size += amount
            data = data[amount:]
            if self.size == self.limit:
                self.close()

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None

    def manifest(self):
        path = self.path.with_name(self.path.name + ".parts")
        path.write_text("\n".join(self.parts) + "\n", encoding="ascii")
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="sixel-video 0.1.0")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--library", help="Path to the libsixel shared library")
    parser.add_argument("--colors", type=int, default=256, choices=range(2, 257), metavar="2..256")
    parser.add_argument("--palette", choices=("frame", "scene"), default="frame",
                        help="Generate palettes per frame or reuse until scene/color drift (default: frame)")
    parser.add_argument("--scene-threshold", type=float, default=35, metavar="0..255",
                        help="Mean RGB difference from the palette's source that refreshes a scene palette (default: 35)")
    parser.add_argument("--denoise", type=float, default=0, metavar="0..1",
                        help="Temporal smoothing strength for small fluctuations; 0 disables it (default)")
    parser.add_argument("--denoise-threshold", type=int, default=12, choices=range(256), metavar="0..255",
                        help="Maximum per-channel RGB fluctuation eligible for smoothing (default: 12)")
    parser.add_argument("--split-mib", type=int, default=0, help="Split compressed output into parts of this size (0 disables splitting)")
    parser.add_argument("--delta", action="store_true", help="Draw only changed pixels between full keyframes (default: full frames)")
    parser.add_argument("--delta-optimize", choices=("raw", "compressed"), default="raw",
                        help="Choose delta/full frames by raw sixel length or trial bzip2 size (default: raw)")
    parser.add_argument("--accelerator", choices=("auto", "numpy", "cython"), default="auto",
                        help="Delta comparison backend; auto uses the optional Cython extension when installed")
    parser.add_argument("--delta-threshold", type=int, default=0, choices=range(101), metavar="0..100",
                        help="Skip color changes within this many sixel RGB percentage points (default: 0, exact)")
    parser.add_argument("--delta-region", choices=("sparse", "rectangle", "adaptive"), default="sparse",
                        help="Try changed pixels, their filled bounding rectangle, or both (default: sparse)")
    parser.add_argument("--keyframe-interval", type=float, default=1.0, metavar="SECONDS",
                        help="Maximum interval between full frames with --delta (default: 1 second)")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Show a progress bar, ETA, conversion speed and size statistics")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="Suppress progress and conversion statistics")
    parser.add_argument("--progress", choices=("auto", "text", "sixel"), default="auto",
                        help="Progress bar style with --verbose; sixel requires terminal support (default: auto)")
    args = parser.parse_args()
    if args.delta_optimize != "raw" and not args.delta:
        parser.error("--delta-optimize compressed requires --delta")
    if args.accelerator != "auto" and not args.delta:
        parser.error("--accelerator requires --delta")
    if not args.delta and (args.delta_threshold or args.delta_region != "sparse"):
        parser.error("--delta-threshold and --delta-region require --delta")
    if not math.isfinite(args.scene_threshold) or not 0 < args.scene_threshold <= 255:
        parser.error("--scene-threshold must be finite and greater than 0, up to 255")
    if not math.isfinite(args.denoise) or not 0 <= args.denoise <= 1:
        parser.error("--denoise must be a finite number from 0 to 1")
    if args.source.resolve() == args.output.resolve():
        parser.error("source and output must be different files")
    if args.split_mib < 0:
        parser.error("--split-mib must be nonnegative")
    if not math.isfinite(args.keyframe_interval) or args.keyframe_interval <= 0:
        parser.error("--keyframe-interval must be a finite positive number")
    try:
        import cv2
    except ImportError:
        parser.error("MP4 conversion requires the opencv-python package")
    capture = cv2.VideoCapture(str(args.source))
    if not capture.isOpened():
        parser.error("Could not open the source video")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        parser.error("Source video must report a positive frame rate")
    encoder = SixelEncoder(args.library, args.colors, args.palette, args.scene_threshold)
    try:
        delta = DeltaEncoder(encoder, max(1, math.floor(fps * args.keyframe_interval)), args.delta_optimize,
                             args.accelerator, args.delta_threshold, args.delta_region) if args.delta else None
    except RuntimeError as error:
        encoder.close()
        capture.release()
        parser.error(str(error))
    compressor = bz2.BZ2Compressor(9)
    output = SplitOutput(args.output, args.split_mib * 1024 * 1024) if args.split_mib else args.output.open("wb")
    count = 0
    compressed_bytes = 0
    sixel_bytes = 0
    started = time.monotonic()
    progress = ConversionProgress(expected_frames, args.library, args.progress) if args.verbose else None
    denoiser = TemporalDenoiser(args.denoise, args.denoise_threshold)
    try:
        if progress:
            progress.update(0, force=True)
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = denoiser.process(rgb)
            data = (delta or encoder).encode(rgb)
            sixel_bytes += len(data)
            compressed = compressor.compress(data)
            output.write(compressed)
            compressed_bytes += len(compressed)
            count += 1
            if progress:
                progress.update(count)
            elif not args.quiet and count % 250 == 0:
                print("Converted {} / {} frames".format(count, expected_frames), flush=True)
        if count != expected_frames:
            raise RuntimeError("Decoded {} frames, expected {}".format(count, expected_frames))
        if progress:
            progress.update(count, force=True, stage="Finishing compression")
        compressed = compressor.flush()
        output.write(compressed)
        compressed_bytes += len(compressed)
        if progress:
            progress.update(count, force=True, stage="Done")
    finally:
        if progress:
            progress.close()
        if delta:
            delta.close()
        encoder.close()
        capture.release()
        output.close()
    destination = output.manifest() if args.split_mib else args.output
    if args.quiet:
        return
    print("Converted {} frames at {}x{}, {:g} fps to {}".format(count, width, height, fps, destination))
    if delta:
        saving = 100 * (1 - delta.output_bytes / delta.full_bytes) if delta.full_bytes else 0
        print("Delta frames: {}; full keyframes: {}; sixel bytes: {} versus {} full ({:.1f}% smaller)".format(
            delta.delta_frames, delta.keyframes, delta.output_bytes, delta.full_bytes, saving))
    if args.verbose:
        elapsed = time.monotonic() - started
        print("Elapsed: {}; speed: {:.1f} fps; sixel: {:,} bytes; bzip2: {:,} bytes ({:.2f} MiB); delta selection: {}".format(
            duration(elapsed), count / elapsed if elapsed else 0, sixel_bytes, compressed_bytes,
            compressed_bytes / (1024 * 1024), args.delta_optimize))
        if delta:
            print("Delta comparison backend: {}".format(delta.accelerator))


if __name__ == "__main__":
    main()
