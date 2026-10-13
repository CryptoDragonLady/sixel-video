# sixel-video

**Turn an MP4 into video your terminal can draw.**

[![Tests](https://github.com/CryptoDragonLady/sixel-video/actions/workflows/test.yml/badge.svg)](https://github.com/CryptoDragonLady/sixel-video/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://github.com/CryptoDragonLady/sixel-video/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Convert once into **SIXEL or Kitty graphics**, then let the terminal render the
result. Keep it simple with full frames, send less data with exact deltas, or
experiment with optional quality and compression controls. Kitty animations can
even carry their own timing: decompress the file into a compatible terminal and
watch it play, without a separate video player.

- **Two native graphics protocols.** SIXEL palettes or lossless Kitty true color.
- **Paint what changes.** Delta frames, periodic keyframes, and region selection.
- **Choose your tradeoff.** Compare terminal bytes with estimated compressed size;
  try denoising and bounded color skipping independently.
- **See conversion progress.** Frame counts, speed, ETA, and a SIXEL progress bar
  when supported, with text fallback.
- **Portable output.** Self-contained files with optional bzip2 compression;
  Kitty payloads use inline transmission, including over SSH.

```sh
# SIXEL: exact updates relative to the quantized full-frame output
sixel-video input.mp4 clip.sixel.bz2 --delta --verbose

# Kitty: full-color patches and timing handled by the terminal
sixel-video input.mp4 clip.kitty.bz2 --format kitty --delta --delta-region adaptive --verbose
bzcat clip.kitty.bz2
```

Kitty's native animation mode requires animation support, beyond basic Kitty
image support. SIXEL and Kitty stream mode require external frame pacing. The
converter preserves source dimensions and decodes video frames only during
conversion; audio is not included.

## Install

Use Python 3.10 or newer. Install libsixel for SIXEL output; Kitty conversion
does not need it. On Debian or Ubuntu:

```sh
sudo apt install libsixel1 python3-venv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install git+https://github.com/CryptoDragonLady/sixel-video.git
```

On macOS, install libsixel with `brew install libsixel`. Windows Terminal can
display SIXEL output through WSL; install the converter and libsixel inside WSL.
This does not imply support for Kitty animations in Windows Terminal.
Use `--library /path/to/libsixel.so` for a nonstandard library location.

## Benchmark presets

`--preset smallest` and `--preset fastest` select settings for `--format sixel`
(the default) or `--format kitty`, using the measured winners from the
[500-frame 720p benchmark](docs/benchmarks/astley-720p.md). `fastest` targets
conversion time. These are fixed option sets derived from that sample; results
depend on your content and machine.

```sh
sixel-video input.mp4 small.sixel.bz2 --preset smallest
sixel-video input.mp4 fast.sixel.bz2 --preset fastest
sixel-video input.mp4 small.kitty.bz2 --format kitty --preset smallest
sixel-video input.mp4 fast.kitty.bz2 --format kitty --preset fastest
```

| Format | Preset | Selected options, relative to defaults | Benchmark row | Stored MiB | Conversion seconds |
| --- | --- | --- | --- | ---: | ---: |
| SIXEL | `smallest` | `--delta --colors 64 --accelerator numpy` | S09 | 48.440 | 20.426 |
| SIXEL | `fastest` | Full frames, 256 colors | S00 | 72.336 | 19.192 |
| Kitty | `smallest` | `--delta --delta-threshold 2` | K16 | 173.078 | 496.450 |
| Kitty | `fastest` | `--kitty-format rgb` with full frames | K01 | 324.671 | 33.140 |

All four use outer bzip2 compression. Kitty uses native animation and zlib on
RGB/RGBA; the smallest Kitty preset uses auto payload selection and sparse
deltas. The smallest SIXEL preset uses per-frame palettes and sparse deltas.
Both delta presets retain the one-second keyframe interval.

**Smallest trades color fidelity for size:** SIXEL uses up to 64 colors per
frame; Kitty permits up to 5 of 255 per RGB channel relative to the decoded
source. The fastest presets use full frames and preserve their format's
default fidelity.

Explicit options override preset settings in either command-line order. For
example, use `--preset smallest --colors 128` to increase the SIXEL palette, or
`--format kitty --preset smallest --delta-threshold 0` for exact Kitty updates.
Existing option compatibility checks still apply: the smallest Kitty preset
requires animation mode because it enables deltas. Omitting `--preset` retains
the usual defaults.

## SIXEL conversion

```sh
sixel-video input.mp4 output.sixel.bz2
sixel-video input.mp4 output.delta.sixel.bz2 --delta --verbose
sixel-video input.mp4 output.storage.sixel.bz2 --delta --delta-optimize compressed --verbose
```

The default mode encodes complete frames. `--delta` omits pixels whose displayed
colors are unchanged and inserts a full keyframe at least every second.
`--keyframe-interval 2` changes that maximum interval to two seconds. SIXEL modes
retain the input dimensions and frame count, using up to 256 colors per frame.
The encoder creates a fresh palette context each frame to avoid stale color
mappings when scenes change.

With `--delta-optimize raw`, the converter chooses between a delta and a full
frame by uncompressed sixel length. This is the default and targets the bytes
sent to the terminal. `--delta-optimize compressed` compares trial bzip2 sizes
instead, targeting the stored file size. Trial compression increases conversion
time. These frame costs are estimates: the final compressor also compresses
patterns across adjacent frames. Always compare the resulting files.

Both delta modes preserve exactly the displayed pixels of full-frame conversion;
color quantization itself is lossy. Full frames are used when a patch needs all
256 palette entries or reaches the keyframe interval.

`--colors 128` reduces the palette to save space at the cost of color fidelity.
`--colors 255` also guarantees room for the delta encoder's unpainted index.

## Kitty conversion

```sh
sixel-video input.mp4 clip.kitty.bz2 --format kitty --verbose
sixel-video input.mp4 clip.delta.kitty.bz2 --format kitty --delta --delta-region adaptive
sixel-video input.mp4 clip.small.kitty.bz2 --format kitty --delta \
  --delta-optimize compressed --kitty-deduplicate --verbose
bzcat clip.small.kitty.bz2
```

Kitty output preserves the decoded RGB values exactly by default. `--kitty-format
auto` compares lossless RGB with PNG, choosing the cheaper payload. RGB uses
native zlib compression by default; PNG includes its own compression. Delta
updates use cropped pixel rectangles or transparent RGBA overlays, with periodic
full keyframes. There is no palette limit.

Native animation loads all frames before starting, then the terminal handles the
source frame timing and one playback loop. `--kitty-loops 0` repeats indefinitely.
`--kitty-deduplicate` requires `--delta` and merges unchanged updates into a
longer frame duration. Loading an entire animation uses terminal image storage;
long or high-resolution clips can exceed its quota.

For basic Kitty image support and bounded terminal storage, use `--kitty-mode
stream`. It outputs independent full-frame lines for an externally paced player;
deltas and native loop controls require animation mode.

See [Kitty options and optimization notes](docs/kitty.md) for the format comparison,
all switches, compatibility limits, and further possibilities such as native
frame composition for motion compensation.

## Additional optimizations

Each option is independent and defaults off. Output remains native terminal
commands. The table below describes SIXEL; Kitty also supports denoising and
bounded color skipping, with the differences described in its documentation.

| Option | Behavior | Tradeoff |
| --- | --- | --- |
| `--palette scene` | Reuse a palette until the mean RGB difference from its source reaches `--scene-threshold` (default 35 of 255). | Reduces palette churn; colors introduced later may be represented less accurately until refresh. |
| `--denoise 0.5` | Smooth small fluctuations using the preceding filtered frame. Changes exceeding `--denoise-threshold` (default 12 of 255 per channel) pass through immediately. | Can soften fine detail; strength ranges from 0 to 1. |
| `--delta-threshold 1` | Skip repainting pixels within one sixel RGB percentage point per channel. | Adds bounded color error relative to full-frame output with the same palette and denoising settings. |
| `--delta-region adaptive` | Try sparse pixels and their filled bounding rectangle, keeping the cheaper candidate or a full frame. | More conversion work; repainting extra pixels can sometimes improve compression. |

`--delta-region sparse` is the default; `--delta-region rectangle` tries only the
rectangle and full frame. Region candidates use the selected `--delta-optimize`
cost. They retain the raster size and leave pixels outside the region unpainted.

Perceptual skipping always compares with the reconstructed image actually on
screen, so small source changes accumulate until repainting is necessary. Its
error bound applies to the quantized, optionally denoised reference, rather than
to the original source video. Scene palettes, denoising and color reduction have
their own quality costs. Full keyframes still refresh every pixel.

For an experimental combination:

```sh
sixel-video input.mp4 output.sixel.bz2 --delta --delta-optimize compressed \
  --palette scene --denoise 0.5 --delta-threshold 1 --delta-region adaptive --verbose
```

Compare each option separately on your content before combining them.

## Progress

```sh
sixel-video input.mp4 output.sixel.bz2 --delta --verbose
sixel-video input.mp4 output.sixel.bz2 --verbose --progress text
sixel-video input.mp4 output.sixel.bz2 --quiet
```

Verbose progress reports the frame count, percentage, ETA and frames per second
on stderr, then reports elapsed time and actual sixel and compressed byte counts.
`--progress auto` probes the terminal with a bounded Primary Device Attributes
query and selects sixel when feature 4 is advertised. `--progress sixel` requests
the same capability check; it falls back to text when support is unavailable.
`--progress text` skips the query. Redirected progress contains no escape codes.
`--quiet` suppresses progress and final statistics.

## SIXEL and stream playback

Each decompressed SIXEL or Kitty stream line is one complete update. Feed those updates to the
terminal at the source video's frame rate. For example, for a 25 fps video:

```sh
python - output.delta.sixel.bz2 <<'PY'
import bz2
import sys
import time

started = time.monotonic()
with bz2.open(sys.argv[1], 'rb') as video:
    for index, frame in enumerate(video):
        time.sleep(max(0, started + index / 25 - time.monotonic()))
        sys.stdout.buffer.write(frame.rstrip(b'\n'))
        sys.stdout.buffer.flush()
PY
```

Delta updates depend on previous frames. A player must retain those updates,
including late ones, or skip forward to a complete keyframe. Plain `bzcat`
decompresses incrementally but does not regulate playback speed. The existing
[rickrollrc player](https://github.com/CryptoDragonLady/rickrollrc) provides
capability detection, frame pacing and audio for its bundled assets.

`--compression none` writes raw protocol bytes instead of bzip2. For native Kitty
animation, `cat clip.kitty` plays this raw file. For paced SIXEL or Kitty streams,
replace `bz2.open` with `open` in the example when using raw output.

For distribution limits, `--split-mib 64` splits the output byte stream and
writes a `.parts` manifest. Concatenating those pieces in manifest order exactly
recreates the single stream; ordinary conversion always produces one file.

## Development

```sh
python -m pip install -e .
python -B -m unittest discover -s tests -v
python benchmarks/convert.py input.mp4 --frames 150 --repeat 3
python benchmarks/convert.py input.mp4 --frames 150 --repeat 3 --format kitty --delta-region adaptive
```

Tests use generated video fixtures and independently interpret both graphics
protocols to verify pixel reconstruction, palette changes, timing, keyframe cadence and terminal
capability handling. GitHub Actions runs them on supported CPython versions.
The benchmark separates decoding, encoding and bzip2 costs and can also emit a
Python profile with `--profile /tmp/sixel-video.prof`.

Read the [500-frame 720p Astley benchmark](docs/benchmarks/astley-720p.md) for
measured sizes, conversion times, frame counts, fidelity, and exact option sets.
To compare the same 40 option sets on your own source:

```sh
python benchmarks/options.py input.mp4 --frames 500 --repeat 3 \
  --json-output /tmp/sixel-video-options.json \
  --document docs/benchmarks/options.md
```

This reports actual output sizes, median conversion times, frame structure, and
sampled reconstruction quality. It also verifies repeated output hashes and
checks that cached source pixels remain unchanged. The complete matrix includes
the optional Cython backend; install it first or use `--only` to select other rows.
Raw receipts and generated animations are kept out of the repository.

The project began as the video converter in rickrollrc. No source videos or
generated animations are included.

## Optional Cython acceleration

The NumPy backend uses vectorized channel comparisons without an axis reduction.
An optional Cython backend performs those comparisons in a single native loop:

```sh
SIXEL_VIDEO_BUILD_CYTHON=1 python -m pip install --no-cache-dir --force-reinstall git+https://github.com/CryptoDragonLady/sixel-video.git
sixel-video input.mp4 output.sixel.bz2 --delta --accelerator cython --verbose
```

Building the extension requires a C compiler and Python development headers
(`sudo apt install build-essential python3-dev` on Debian or Ubuntu). Ordinary installs work without
one. `--accelerator auto` uses the extension when installed and otherwise uses
NumPy. `--accelerator numpy` forces the portable backend for comparisons. The
backends produce identical output bytes; the benchmark can measure their impact
on your source video. Most conversion work still happens in libsixel, OpenCV and
libbzip2, so speeding up pixel comparisons only speeds up part of the pipeline.

PyPy has not been validated for the complete converter. OpenCV and NumPy depend
on native extension compatibility, so its JIT is not an automatic speedup for
this workload. See [PyPy's extension guidance](https://doc.pypy.org/faq.html#do-c-extension-modules-work-with-pypy).
