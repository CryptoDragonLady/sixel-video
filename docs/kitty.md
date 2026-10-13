# Kitty graphics: full-color video, rendered by the terminal

SIXEL and Kitty can both carry deltas without an external video decoder. Kitty
adds direct RGB/RGBA and PNG transmission, pixel offsets, and native animation
timing. These features let the converter avoid palette quantization and put
playback scheduling inside the terminal.

## Try it

```sh
sixel-video input.mp4 clip.kitty.bz2 --format kitty --delta \
  --delta-region adaptive --verbose
bzcat clip.kitty.bz2
```

The default loads an animation, places it at the top-left of the terminal, and
plays it once. Make the window large enough for the source dimensions. Source
audio is not converted. Basic Kitty image support alone is insufficient: native
animation needs the frame-loading and animation-control actions.

## Which optimizations transfer?

| Technique | SIXEL | Kitty output in this project |
| --- | --- | --- |
| Exact deltas | Omit unchanged quantized colors. | Copy a previous native frame as the base; overlay a cropped RGB rectangle or sparse RGBA pixels. |
| Periodic keyframes | Refresh the complete raster. | Store a complete frame without a dependency on the preceding frame. |
| Compression-aware selection | Trial bzip2 costs for full and delta candidates. | Same selection, also comparing RGB and PNG payloads when `auto` is selected. |
| Temporal denoising | Smooth small RGB fluctuations before quantization. | Same preprocessing, before lossless RGB/PNG encoding. |
| Bounded color skipping | Compare reconstructed RGB percentages. | Compare reconstructed 8-bit RGB; convert the percentage threshold to `floor(threshold * 255 / 100)` channel values. |
| Palette reuse or fewer colors | Useful options with a quality tradeoff. | Not applied: Kitty has no SIXEL palette constraint. |
| Native payload compression | SIXEL run-length encoding, plus optional outer bzip2. | Zlib-compressed RGB/RGBA or PNG, plus optional outer bzip2. |
| Repeated-frame duration | Requires the paced player to preserve timing. | Optional deduplication extends the preceding frame's native duration. |
| Native scheduling | Needs a pacing process. | Frame gaps and loop controls travel in the animation itself. |

The default delta threshold is zero. This reproduces each decoded RGB frame
exactly in Kitty output, including erasing moving objects and changing colors.
Lossy options remain opt-in. With a nonzero threshold, comparison uses the actual
reconstruction, so small consecutive changes eventually trigger repainting.
The bound applies to the optionally denoised reference; denoising adds its own
quality cost.

## Switches

| Switch | Default | Purpose |
| --- | --- | --- |
| `--format kitty` | SIXEL output | Select Kitty graphics. |
| `--kitty-mode animation` | `animation` | Load frames and let the terminal schedule playback. |
| `--kitty-mode stream` | — | Independent full-frame lines; pace externally. No deltas, deduplication, or native loops. |
| `--kitty-format auto` | `auto` | Compare RGB/RGBA with PNG using the selected cost. |
| `--kitty-format rgb` | — | Use raw RGB/RGBA, optionally compressed with zlib. |
| `--kitty-format png` | — | Use lossless PNG with its built-in DEFLATE compression. |
| `--kitty-compression zlib` | `zlib` | Compress RGB/RGBA before base64 transmission. |
| `--kitty-compression none` | — | Send RGB/RGBA without zlib; PNG retains its built-in compression. |
| `--compression bzip2` | `bzip2` | Compress the complete protocol stream for storage. |
| `--compression none` | — | Save directly renderable escape codes. |
| `--delta` | Off | Consider overlays between full keyframes. |
| `--delta-region sparse` | `sparse` | Use alpha-zero pixels for unchanged areas inside a cropped bounding box. |
| `--delta-region rectangle` | — | Repaint the entire cropped bounding rectangle. |
| `--delta-region adaptive` | — | Try sparse, rectangular, and full candidates. |
| `--delta-optimize raw` | `raw` | Select by serialized terminal bytes. |
| `--delta-optimize compressed` | — | Select by estimated bzip2 size. Requires `--delta`. |
| `--delta-threshold 1` | `0` | Tolerate at most 2 of 255 per RGB channel, relative to the same denoised reference. Requires `--delta`. |
| `--keyframe-interval 2` | `1` second | Maximum interval between full frames. |
| `--kitty-deduplicate` | Off | Extend the prior frame when no pixel exceeds the tolerance; requires animation deltas. |
| `--kitty-loops 0` | `1` | Loop indefinitely; positive values play that many times. |
| `--kitty-image-id 123` | `42` | Select the image ID to avoid replacing another application's image. |

`--denoise`, `--denoise-threshold`, `--verbose`, `--quiet`, `--progress`, and
`--split-mib` work for both protocols. Progress can use SIXEL if the terminal
advertises it; otherwise it uses text. Kitty-only options require `--format kitty`.
`--colors`, `--palette`, and `--scene-threshold` are SIXEL settings; nondefault
values are rejected for Kitty. `--accelerator` selects the optional SIXEL
comparison backend; Kitty uses NumPy.

## Measure your clip

```sh
python benchmarks/convert.py input.mp4 --frames 500 --repeat 3 --format kitty \
  --kitty-format rgb --delta-region rectangle
python benchmarks/convert.py input.mp4 --frames 500 --repeat 3 --format kitty \
  --kitty-format auto --delta-region adaptive
```

Each benchmark reports full-frame, raw-cost delta, and compressed-cost delta
results using identical decoded RGB frames. Encoding time includes payload
compression and candidate selection; final bzip2 time is reported separately.
Compare actual final sizes. PNG filters can help some content; zlib on RGB can
win elsewhere. Nested compression may add little. Trial per-frame bzip2 costs
cannot predict all patterns across adjacent frames. Full-color Kitty output can
be larger than color-quantized SIXEL output: they preserve different information.
`auto` and adaptive regions encode multiple candidates per frame. For faster
conversion with fewer candidates, try `--kitty-format rgb --delta-region rectangle`;
this can produce larger files.

For one 256×144, 25 fps clip, converting the first 500 frames with lossless
`--kitty-format auto`, zlib, and one-second keyframes gave:

| Mode | Terminal bytes | Final bzip2 bytes |
| --- | ---: | ---: |
| Full frames | 19,573,776 | 14,706,546 |
| Deltas, adaptive regions, raw selection | 17,713,195 | 13,305,792 |
| Deltas, adaptive regions, compressed selection | 17,713,195 | 13,305,792 |

That is about 9.5% less stored data with exact reconstruction. Both selection
heuristics picked the same updates for this sample. This is a sample result,
not a promised reduction for other videos or for the complete clip.

The [500-frame 720p benchmark](benchmarks/astley-720p.md) compares 40 SIXEL and
Kitty configurations, with three runs each. At 1280×720, exact adaptive Kitty
deltas reduced the bzip2 size by 5.03%, from 190.923 to 181.323 MiB, while median
conversion time increased from 256.994 to 809.853 seconds. It includes RGB/PNG,
compression, region, tolerance, denoising, and deduplication comparisons.

## Other possibilities

Kitty's native **frame composition** command can copy a pixel rectangle from
one stored frame to another. A converter could estimate motion, copy matching
regions, and transmit the remaining changed pixels. This is a path toward motion
compensation without a custom playback decoder, but it needs exact reconstruction
checks, command-overhead accounting, and storage testing. Motion search and
composition output are not implemented here yet.

Multiple rectangle updates could improve sparse scenes with distant moving
objects. The current implementation selects one cropped overlay per stored
frame; tiling would trade smaller payloads against more protocol commands.

File and shared-memory transmission can reduce local transfer overhead, but
would depend on the terminal accessing external assets. This converter uses
inline payloads to keep each output file self-contained and transferable.

Native animation stores the clip in the terminal before starting. Kitty applies
image storage quotas; use shorter clips, smaller source dimensions, or full-frame
stream mode for long videos. Stream mode requires pacing and avoids retaining an
entire animation. The converter does not automatically probe the playback
terminal, wrap commands for multiplexers, or scale video to its dimensions.

Timing is rounded cumulatively to milliseconds, preserving fractional frame
rates without rounding every frame to the same duration. Variable frame timestamps
are not preserved; conversion uses the source's reported frame rate.

Protocol details: [Kitty graphics specification](https://sw.kovidgoyal.net/kitty/graphics-protocol/),
[native animation](https://sw.kovidgoyal.net/kitty/graphics-protocol/#animation),
and [frame composition](https://sw.kovidgoyal.net/kitty/graphics-protocol/#composing-animation-frames).
