# 500-frame 720p Astley benchmark

Measured on 2026-10-12. The tables compare actual emitted bytes and measured conversion work.

## Dataset and method

- Source: `NeverGonnaGiveYouUp720p.mp4`; SHA-256 `bef2dfb1d128eccf6b953fc2385b02add0becebe33f73e0632aaf5adee7ad252`.
- Frames 0–499, 1280×720, 25 fps: 20 seconds of video, decoded directly without resizing or an intermediate video transcode.
- sixel-video 0.2.0; converter commit `f40953e2f1002d901e54276f104c45e7d7d96b66`.
- 3 sequential repetitions per configuration, after a 3-frame warm-up; tables report medians and observed ranges.
- Decoding, RGB conversion and frame hashing took 1.702 seconds, once, before reusing the cached frames. Timings include denoising, encoding, candidate selection, and outer compression; exclude source decoding, filesystem writes, and reconstruction checks.
- Host: Linux x86_64; 10 reported CPUs, `AMD Ryzen 9 7900 12-Core Processor`. Python 3.13.5, NumPy 2.5.0, OpenCV 4.13.0. OpenCV/FFmpeg decoding use one thread; other host activity is uncontrolled.
- System compression/graphics packages: `libbz2-1.0 1.0.8-6`; `libsixel1 1.10.5-1`.
- Stored bytes use one continuous bzip2 level-9 stream, including its final flush, except rows explicitly using `--compression none`. Generated animations are not saved.
- Default keyframe interval is one second; SIXEL uses 256 colors and NumPy unless noted; Kitty uses native animation, auto payload selection, and zlib on RGB/RGBA unless noted.
- Output counts and SHA-256 must agree across repetitions. Independent interpreters reconstruct sample frames 0, 99, 199, 299, 399, 499 from their preceding full keyframe and verify delta error bounds.
- The cached RGB frame hash is checked after each configuration to verify that every run used the same source pixels.
- MAE, PSNR and maximum error compare those decoded samples with the source RGB. SIXEL percentages are mapped to 8-bit RGB with nearest rounding; terminal-specific rounding can differ by one channel value. Quality figures are sampled, not whole-clip measurements.

## How to read the results

“Wire” is the full emitted protocol stream after outer decompression; it still contains Kitty’s native zlib/PNG payload compression and base64. “Stored” is the saved file size. MiB is 1,048,576 bytes.

Wire counts include the framing newline in SIXEL and Kitty stream mode. Paced players normally remove that one byte per update before sending it to the terminal; native Kitty animation has no framing newlines.

SIXEL exact deltas preserve the corresponding quantized full-frame output. Kitty preserves decoded RGB exactly when denoising and color tolerance are disabled. These formats retain different color information, so their sizes are not an equal-quality codec comparison.

A positive size reduction means smaller than the protocol’s default full-frame baseline. Full/Delta counts refer to source updates; Kitty merges can reduce the stored animation frame count. MAE is mean absolute per-channel error; PSNR is `10 log10(255² / MSE)`. Infinite PSNR means zero sampled RGB error.

This matrix focuses on settings that affect image encoding, compression, or frame structure. Verbosity/progress control status output; image IDs and loop counts control playback metadata. Splitting partitions the same byte stream rather than changing compression.

## SIXEL

### Output sizes

| ID | Configuration | Wire bytes | Stored bytes | Stored MiB | Reduction vs full |
| --- | --- | ---: | ---: | ---: | ---: |
| S00 | Full frames, 256 colors | 173,536,852 | 75,849,813 | 72.336 | 0.00% |
| S01 | Exact sparse deltas, NumPy | 162,168,073 | 72,344,255 | 68.993 | 4.62% |
| S02 | Compressed-cost sparse deltas | 162,347,705 | 72,209,748 | 68.865 | 4.80% |
| S03 | Rectangle deltas | 173,539,352 | 75,846,818 | 72.333 | 0.00% |
| S04 | Adaptive deltas | 162,168,073 | 72,344,255 | 68.993 | 4.62% |
| S05 | Adaptive, compressed cost | 162,347,705 | 72,209,748 | 68.865 | 4.80% |
| S06 | Exact sparse deltas, Cython | 162,168,073 | 72,344,255 | 68.993 | 4.62% |
| S07 | 255-color deltas | 162,043,247 | 72,290,814 | 68.942 | 4.69% |
| S08 | 128-color deltas | 140,545,740 | 62,687,580 | 59.784 | 17.35% |
| S09 | 64-color deltas | 115,299,636 | 50,792,706 | 48.440 | 33.04% |
| S10 | Scene palette, threshold 35 | 158,894,695 | 69,634,143 | 66.408 | 8.19% |
| S11 | Scene palette, threshold 15 | 163,968,259 | 72,359,541 | 69.007 | 4.60% |
| S12 | Denoise 0.5 | 163,950,331 | 74,607,525 | 71.151 | 1.64% |
| S13 | Color tolerance 1% | 161,789,434 | 72,223,734 | 68.878 | 4.78% |
| S14 | Color tolerance 2% | 160,478,636 | 71,741,806 | 68.418 | 5.42% |
| S15 | Keyframes within 0.5 s | 162,611,251 | 72,524,453 | 69.165 | 4.38% |
| S16 | Keyframes within 2 s | 161,994,959 | 72,279,615 | 68.931 | 4.71% |
| S17 | Keyframes within 5 s | 161,830,325 | 72,207,913 | 68.863 | 4.80% |
| S18 | Combined lossy controls | 159,599,213 | 71,270,265 | 67.969 | 6.04% |
| S19 | Exact deltas, no outer bzip2 | 162,168,073 | 162,168,073 | 154.656 | -113.80% |

### Conversion time

| ID | Encode s | Outer compression/pass-through s | Total median s | Total range s | Conversion fps |
| --- | ---: | ---: | ---: | ---: | ---: |
| S00 | 12.350 | 6.804 | 19.192 | 19.081–19.193 | 26.05 |
| S01 | 27.079 | 6.391 | 33.455 | 33.453–33.542 | 14.95 |
| S02 | 39.616 | 6.394 | 46.010 | 45.985–46.060 | 10.87 |
| S03 | 28.784 | 6.863 | 35.647 | 35.622–35.762 | 14.03 |
| S04 | 38.487 | 6.394 | 44.888 | 44.815–44.996 | 11.14 |
| S05 | 58.181 | 6.392 | 64.574 | 64.484–64.658 | 7.74 |
| S06 | 27.089 | 6.405 | 33.494 | 33.304–33.550 | 14.93 |
| S07 | 26.991 | 6.379 | 33.370 | 33.334–33.380 | 14.98 |
| S08 | 20.218 | 5.609 | 25.827 | 25.715–25.878 | 19.36 |
| S09 | 15.839 | 4.584 | 20.426 | 20.397–20.435 | 24.48 |
| S10 | 163.896 | 6.419 | 170.307 | 170.230–170.727 | 2.94 |
| S11 | 135.036 | 6.558 | 141.602 | 141.424–141.607 | 3.53 |
| S12 | 31.849 | 6.475 | 38.343 | 38.176–41.419 | 13.04 |
| S13 | 27.452 | 6.384 | 33.849 | 33.823–33.906 | 14.77 |
| S14 | 27.436 | 6.324 | 33.756 | 33.690–33.766 | 14.81 |
| S15 | 26.376 | 6.393 | 32.772 | 32.721–32.793 | 15.26 |
| S16 | 26.538 | 6.389 | 32.927 | 32.921–32.970 | 15.19 |
| S17 | 26.582 | 6.381 | 32.965 | 32.882–32.968 | 15.17 |
| S18 | 202.322 | 6.437 | 208.762 | 208.467–210.609 | 2.40 |
| S19 | 26.544 | 0.000 | 26.545 | 26.502–26.589 | 18.84 |

### Frame structure and sampled fidelity

| ID | Full / delta updates | Palette refreshes | RGB MAE | PSNR dB | Maximum RGB error |
| --- | ---: | --- | ---: | ---: | ---: |
| S00 | 500 / 0 | 500 | 2.409 | 36.54 | 73 |
| S01 | 333 / 167 | 500 | 2.409 | 36.54 | 73 |
| S02 | 360 / 140 | 500 | 2.409 | 36.54 | 73 |
| S03 | 500 / 0 | 500 | 2.409 | 36.54 | 73 |
| S04 | 333 / 167 | 500 | 2.409 | 36.54 | 73 |
| S05 | 360 / 140 | 500 | 2.409 | 36.54 | 73 |
| S06 | 333 / 167 | 500 | 2.409 | 36.54 | 73 |
| S07 | 332 / 168 | 500 | 2.409 | 36.54 | 73 |
| S08 | 371 / 129 | 500 | 2.794 | 34.78 | 93 |
| S09 | 424 / 76 | 500 | 3.364 | 32.73 | 88 |
| S10 | 293 / 207 | 20 | 1.937 | 37.58 | 73 |
| S11 | 338 / 162 | 123 | 1.980 | 37.85 | 73 |
| S12 | 324 / 176 | 500 | 2.561 | 35.95 | 78 |
| S13 | 327 / 173 | 500 | 2.409 | 36.54 | 73 |
| S14 | 315 / 185 | 500 | 2.411 | 36.53 | 73 |
| S15 | 339 / 161 | 500 | 2.409 | 36.54 | 73 |
| S16 | 331 / 169 | 500 | 2.409 | 36.54 | 73 |
| S17 | 330 / 170 | 500 | 2.409 | 36.54 | 73 |
| S18 | 294 / 206 | 20 | 2.139 | 36.94 | 73 |
| S19 | 333 / 167 | 500 | 2.409 | 36.54 | 73 |

## Kitty

### Output sizes

| ID | Configuration | Wire bytes | Stored bytes | Stored MiB | Reduction vs full |
| --- | --- | ---: | ---: | ---: | ---: |
| K00 | Full frames, auto payload | 266,183,613 | 200,196,998 | 190.923 | 0.00% |
| K01 | Full RGB, zlib | 453,404,986 | 340,442,459 | 324.671 | -70.05% |
| K02 | Full RGB, no zlib | 1,850,862,481 | 299,568,270 | 285.691 | -49.64% |
| K03 | Full PNG | 266,183,693 | 200,207,850 | 190.933 | -0.01% |
| K04 | Full PNG, no outer bzip2 | 266,183,693 | 266,183,693 | 253.853 | -32.96% |
| K05 | Auto payload, paced stream | 265,927,184 | 200,203,436 | 190.929 | -0.00% |
| K06 | Exact auto sparse deltas | 259,459,556 | 195,139,642 | 186.100 | 2.53% |
| K07 | Auto rectangle deltas | 257,777,089 | 193,986,027 | 184.999 | 3.10% |
| K08 | Auto adaptive deltas | 252,673,107 | 190,130,772 | 181.323 | 5.03% |
| K09 | Auto adaptive, compressed cost | 252,673,203 | 190,140,107 | 181.332 | 5.02% |
| K10 | Merge repeated frames | 259,459,556 | 195,139,642 | 186.100 | 2.53% |
| K11 | RGB sparse deltas | 418,169,627 | 314,031,451 | 299.484 | -56.86% |
| K12 | RGB rectangle deltas | 445,992,919 | 335,239,584 | 319.709 | -67.45% |
| K13 | PNG sparse deltas | 259,459,636 | 195,140,949 | 186.101 | 2.53% |
| K14 | Denoise 0.5 | 339,616,093 | 255,497,553 | 243.661 | -27.62% |
| K15 | Color tolerance 1% | 252,926,974 | 190,225,973 | 181.414 | 4.98% |
| K16 | Color tolerance 2% | 241,325,339 | 181,485,435 | 173.078 | 9.35% |
| K17 | Keyframes within 2 s | 259,334,445 | 195,044,955 | 186.009 | 2.57% |
| K18 | Combined lossy controls | 316,148,495 | 237,877,380 | 226.858 | -18.82% |
| K19 | Exact auto deltas, no outer bzip2 | 259,459,556 | 259,459,556 | 247.440 | -29.60% |

### Conversion time

| ID | Encode s | Outer compression/pass-through s | Total median s | Total range s | Conversion fps |
| --- | ---: | ---: | ---: | ---: | ---: |
| K00 | 245.569 | 11.420 | 256.994 | 256.755–257.068 | 1.95 |
| K01 | 14.123 | 19.006 | 33.140 | 33.119–33.151 | 15.09 |
| K02 | 1.769 | 62.137 | 63.906 | 63.790–63.950 | 7.82 |
| K03 | 231.098 | 11.403 | 242.487 | 242.426–242.976 | 2.06 |
| K04 | 231.312 | 0.000 | 231.312 | 231.196–231.326 | 2.16 |
| K05 | 245.233 | 11.367 | 256.595 | 256.555–256.786 | 1.95 |
| K06 | 554.329 | 11.118 | 565.447 | 565.327–565.715 | 0.88 |
| K07 | 503.117 | 11.016 | 514.133 | 513.990–514.504 | 0.97 |
| K08 | 799.200 | 10.790 | 809.853 | 809.733–810.279 | 0.62 |
| K09 | 913.782 | 10.692 | 924.461 | 924.398–924.506 | 0.54 |
| K10 | 554.254 | 10.963 | 565.221 | 564.870–565.258 | 0.88 |
| K11 | 63.256 | 17.584 | 80.830 | 80.786–80.887 | 6.19 |
| K12 | 29.610 | 18.793 | 48.394 | 48.331–48.478 | 10.33 |
| K13 | 496.794 | 10.957 | 507.756 | 507.542–507.995 | 0.98 |
| K14 | 702.525 | 14.318 | 716.871 | 716.751–720.982 | 0.70 |
| K15 | 537.633 | 10.698 | 548.323 | 548.258–548.775 | 0.91 |
| K16 | 486.270 | 10.179 | 496.450 | 496.377–496.480 | 1.01 |
| K17 | 554.505 | 10.952 | 565.457 | 565.349–565.499 | 0.88 |
| K18 | 1038.801 | 13.305 | 1052.106 | 1051.899–1054.342 | 0.48 |
| K19 | 554.133 | 0.000 | 554.133 | 553.975–554.705 | 0.90 |

### Frame structure and sampled fidelity

| ID | Full / delta updates | Stored / merged frames; PNG / RGB / RGBA payloads | RGB MAE | PSNR dB | Maximum RGB error |
| --- | ---: | --- | ---: | ---: | ---: |
| K00 | 500 / 0 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K01 | 500 / 0 | 500 / 0; 0 / 500 / 0 | 0.000 | ∞ | 0 |
| K02 | 500 / 0 | 500 / 0; 0 / 500 / 0 | 0.000 | ∞ | 0 |
| K03 | 500 / 0 | 500 / 0; 500 / 0 / 0 | 0.000 | ∞ | 0 |
| K04 | 500 / 0 | 500 / 0; 500 / 0 / 0 | 0.000 | ∞ | 0 |
| K05 | 500 / 0 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K06 | 403 / 97 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K07 | 20 / 480 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K08 | 20 / 480 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K09 | 20 / 480 | 500 / 0; 500 / 0 / 0 | 0.000 | ∞ | 0 |
| K10 | 403 / 97 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K11 | 317 / 183 | 500 / 0; 0 / 317 / 183 | 0.000 | ∞ | 0 |
| K12 | 20 / 480 | 500 / 0; 0 / 500 / 0 | 0.000 | ∞ | 0 |
| K13 | 403 / 97 | 500 / 0; 500 / 0 / 0 | 0.000 | ∞ | 0 |
| K14 | 443 / 57 | 500 / 0; 499 / 1 / 0 | 0.708 | 44.77 | 6 |
| K15 | 349 / 151 | 500 / 0; 499 / 1 / 0 | 0.055 | 58.75 | 2 |
| K16 | 285 / 215 | 500 / 0; 498 / 1 / 1 | 0.151 | 51.87 | 5 |
| K17 | 402 / 98 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |
| K18 | 20 / 480 | 500 / 0; 473 / 0 / 27 | 0.763 | 44.44 | 7 |
| K19 | 403 / 97 | 500 / 0; 499 / 1 / 0 | 0.000 | ∞ | 0 |

## Findings from this sample

- SIXEL default exact deltas changed wire bytes by -6.55% and stored bytes by -4.62% versus full frames.
- Smallest measured SIXEL result: S09 (48.440 MiB; sampled MAE 3.364). Read its settings and quality costs before choosing it.
- Kitty default exact deltas changed wire bytes by -2.53% and stored bytes by -2.53% versus full frames.
- Smallest measured Kitty result: K16 (173.078 MiB; sampled MAE 0.151). Read its settings and quality costs before choosing it.
- NumPy and Cython produced identical bytes. Cython changed total median conversion time by +0.12% on this sample.
- Smallest sampled-exact Kitty result: K08 (181.323 MiB); all Kitty rows without denoising/tolerance reconstructed the sampled RGB exactly.
- Kitty deduplication merged 0 source updates in K10; its benefit depends on genuinely repeated or tolerance-equivalent frames.

### Practical tradeoffs

- Exact SIXEL sparse deltas (S01) saved 4.62% after bzip2, but increased median conversion time from 19.192 to 33.455 seconds. The Cython comparison loop did not materially change that total on this host.
- Compressed-cost SIXEL selection (S02) emitted 179,632 more wire bytes than raw-cost selection (S01), yet stored 134,507 fewer bytes after bzip2. Selecting by terminal bytes and selecting by compressed size can favor different updates.
- Kitty adaptive regions (K08) were the smallest exact option tested: 181.323 MiB, versus 190.923 MiB for full frames. Median conversion time rose from 256.994 to 809.853 seconds. Choosing RGB with zlib (K01) converted in 33.140 seconds, but produced a larger 324.671 MiB file.
- Per-frame compression estimates are a heuristic. Kitty compressed-cost adaptive selection (K09) took 924.461 seconds and stored 9,335 more bytes than raw-cost adaptive selection (K08). It did not improve the complete continuous bzip2 stream here.
- Reducing SIXEL to 64 colors (S09) gave the largest measured SIXEL reduction, 33.04%, with sampled RGB MAE increasing from 2.409 to 3.364. Kitty's 2% tolerance (K16) saved 9.35%, with sampled maximum RGB error of 5; these controls trade fidelity for size.
- Denoising increased size relative to exact sparse deltas in both protocols: SIXEL S12 was 71.151 MiB versus S01's 68.993 MiB, and Kitty K14 was 243.661 MiB versus K06's 186.100 MiB. Repeated-frame merging found no duplicates in this segment. Combining controls did not automatically improve results.

The selected opening segment does not represent every scene in the complete video. Timings describe this host and exclude playback; converter fps does not prove terminal rendering throughput. Native Kitty animation loads frames before playing, while SIXEL and Kitty stream output need a pacing process.

## Exact option sets

All options are relative to the converter defaults, except SIXEL comparison uses NumPy explicitly unless the Cython row is selected. Denoising uses the default threshold of 12/255. PNG retains built-in compression even when Kitty RGB compression is disabled.

| ID | Converter options |
| --- | --- |
| S00 | `(defaults)` |
| S01 | `--delta --accelerator numpy` |
| S02 | `--delta --delta-optimize compressed --accelerator numpy` |
| S03 | `--delta --delta-region rectangle --accelerator numpy` |
| S04 | `--delta --delta-region adaptive --accelerator numpy` |
| S05 | `--delta --delta-region adaptive --delta-optimize compressed --accelerator numpy` |
| S06 | `--delta --accelerator cython` |
| S07 | `--delta --colors 255 --accelerator numpy` |
| S08 | `--delta --colors 128 --accelerator numpy` |
| S09 | `--delta --colors 64 --accelerator numpy` |
| S10 | `--delta --palette scene --accelerator numpy` |
| S11 | `--delta --palette scene --scene-threshold 15 --accelerator numpy` |
| S12 | `--delta --denoise 0.5 --accelerator numpy` |
| S13 | `--delta --delta-threshold 1 --accelerator numpy` |
| S14 | `--delta --delta-threshold 2 --accelerator numpy` |
| S15 | `--delta --keyframe-interval 0.5 --accelerator numpy` |
| S16 | `--delta --keyframe-interval 2 --accelerator numpy` |
| S17 | `--delta --keyframe-interval 5 --accelerator numpy` |
| S18 | `--delta --palette scene --denoise 0.5 --delta-threshold 1 --delta-region adaptive --delta-optimize compressed --accelerator numpy` |
| S19 | `--delta --compression none --accelerator numpy` |
| K00 | `--format kitty` |
| K01 | `--format kitty --kitty-format rgb` |
| K02 | `--format kitty --kitty-format rgb --kitty-compression none` |
| K03 | `--format kitty --kitty-format png` |
| K04 | `--format kitty --kitty-format png --compression none` |
| K05 | `--format kitty --kitty-mode stream` |
| K06 | `--format kitty --delta` |
| K07 | `--format kitty --delta --delta-region rectangle` |
| K08 | `--format kitty --delta --delta-region adaptive` |
| K09 | `--format kitty --delta --delta-region adaptive --delta-optimize compressed` |
| K10 | `--format kitty --delta --kitty-deduplicate` |
| K11 | `--format kitty --delta --kitty-format rgb` |
| K12 | `--format kitty --delta --kitty-format rgb --delta-region rectangle` |
| K13 | `--format kitty --delta --kitty-format png` |
| K14 | `--format kitty --delta --denoise 0.5` |
| K15 | `--format kitty --delta --delta-threshold 1` |
| K16 | `--format kitty --delta --delta-threshold 2` |
| K17 | `--format kitty --delta --keyframe-interval 2` |
| K18 | `--format kitty --delta --delta-region adaptive --delta-optimize compressed --denoise 0.5 --delta-threshold 1 --kitty-deduplicate` |
| K19 | `--format kitty --delta --compression none` |

## Reproduce

Use the same source SHA-256, converter revision, library versions, and optional Cython extension. No source video or generated animation is bundled.

```sh
python benchmarks/options.py NeverGonnaGiveYouUp720p.mp4 --frames 500 --repeat 3 \
  --json-output /tmp/astley-720p-results.json \
  --document docs/benchmarks/astley-720p.md
```

`--only S01,S06` selects configurations by ID. `--resume` reuses completed configurations from the JSON receipt after checking the dataset, code, options, and repetition count. Resume timing results can span different host loads.

See [conversion options](../../README.md) and [Kitty optimization notes](../kitty.md) for playback and quality tradeoffs.
