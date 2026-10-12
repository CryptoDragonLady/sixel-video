"""Self-contained Kitty graphics streams, using only native terminal commands."""

import base64
import bz2
import math
import zlib

import cv2
import numpy as np


def command(header, payload=b''):
    """Encode inline data in protocol-compliant, at most 4096-byte chunks."""
    encoded = base64.b64encode(payload)
    chunks = [encoded[index:index + 4096] for index in range(0, len(encoded), 4096)] or [b'']
    output = []
    for index, chunk in enumerate(chunks):
        fields = dict(header) if index == 0 else {'q': 2}
        if index and header.get('a') == 'f':
            fields['a'] = 'f'
        if payload:
            fields['m'] = int(index + 1 < len(chunks))
        control = ','.join('{}={}'.format(key, value) for key, value in fields.items()).encode('ascii')
        output.append(b'\x1b_G' + control + b';' + chunk + b'\x1b\\')
    return b''.join(output)


class KittyEncoder:
    """Lossless RGB/PNG frames, optional overlays and terminal-driven timing."""

    def __init__(self, fps, delta=False, keyframe_frames=25, optimize='raw', threshold=0,
                 region='sparse', payload_format='auto', compression='zlib', mode='animation',
                 image_id=42, loops=1, deduplicate=False):
        self.fps = fps
        self.delta = delta
        self.keyframe_frames = keyframe_frames
        self.optimize = optimize
        self.threshold = math.floor(threshold * 255 / 100)
        self.region = region
        self.payload_format = payload_format
        self.compression = compression
        self.mode = mode
        self.image_id = image_id
        self.loops = loops
        self.deduplicate = deduplicate
        self.previous = None
        self.frames = self.stored_frames = self.delta_frames = self.keyframes = 0
        self.last_keyframe = 0
        self.full_bytes = self.output_bytes = self.repeated_frames = 0
        self.gap = 0

    def control(self, **fields):
        return command(dict(a='a', i=self.image_id, q=2, **fields))

    def cost(self, data):
        return len(bz2.compress(data, compresslevel=9)) if self.optimize == 'compressed' else len(data)

    def transmit(self, pixels, fields):
        candidates = []
        if self.payload_format != 'png':
            raw = pixels.tobytes()
            header = dict(fields, f=pixels.shape[2] * 8, s=pixels.shape[1], v=pixels.shape[0])
            if self.compression == 'zlib':
                raw = zlib.compress(raw, 9)
                header['o'] = 'z'
            candidates.append(command(header, raw))
        if self.payload_format != 'rgb':
            order = [2, 1, 0, 3] if pixels.shape[2] == 4 else [2, 1, 0]
            ok, png = cv2.imencode('.png', pixels[:, :, order], [cv2.IMWRITE_PNG_COMPRESSION, 9])
            if not ok:
                raise RuntimeError('Could not encode Kitty PNG payload')
            # PNG already uses DEFLATE. Avoid a redundant outer zlib layer.
            candidates.append(command(dict(fields, f=100), png.tobytes()))
        return min(candidates, key=self.cost)

    def encode(self, rgb):
        if self.previous is not None and self.previous.shape != rgb.shape:
            raise RuntimeError('Kitty animation dimensions must remain constant')
        gap = max(1, round((self.frames + 1) * 1000 / self.fps) - round(self.frames * 1000 / self.fps))
        root = self.frames == 0
        fields = dict(a=('T' if self.mode == 'stream' else 't') if root or self.mode == 'stream' else 'f',
                      i=self.image_id, q=2)
        if self.mode == 'stream':
            fields.update(p=1, C=1)
        elif not root:
            fields.update(z=gap, X=1)
        full = self.transmit(rgb, fields)
        if root and self.mode == 'animation':
            full += self.control(r=1, z=gap)
        elif self.mode == 'stream':
            full = b'\x1b[H' + full + b'\n'
        data = full
        keyframe = root or not self.delta or self.frames - self.last_keyframe >= self.keyframe_frames
        painted = None
        duplicate = False
        if self.delta and not keyframe:
            # Compare with the actual reconstruction, so tolerated drift cannot accumulate.
            difference = np.abs(rgb.astype(np.int16) - self.previous.astype(np.int16))
            changed = ((difference[:, :, 0] > self.threshold) | (difference[:, :, 1] > self.threshold)
                       | (difference[:, :, 2] > self.threshold))
            if not changed.any() and self.deduplicate:
                duplicate = True
                self.gap += gap
                data = self.control(r=self.stored_frames, z=self.gap)
            else:
                if changed.any():
                    ys, xs = np.nonzero(changed)
                    x, y, right, bottom = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
                else:
                    x = y = 0
                    right = bottom = 1
                overlay = dict(fields, c=self.stored_frames, x=int(x), y=int(y))
                region = np.zeros_like(changed)
                region[y:bottom, x:right] = True
                candidates = [(full, None)]
                if self.region != 'sparse':
                    candidates.append((self.transmit(rgb[y:bottom, x:right], overlay), region))
                if self.region != 'rectangle':
                    sparse = np.zeros((bottom - y, right - x, 4), dtype=np.uint8)
                    mask = changed[y:bottom, x:right]
                    sparse[:, :, :3] = np.where(mask[:, :, None], rgb[y:bottom, x:right], 0)
                    sparse[:, :, 3] = mask.astype(np.uint8) * 255
                    # Transparent pixels must alpha-blend with the base, never erase it.
                    candidates.append((self.transmit(sparse, dict(overlay, X=0)), changed))
                data, painted = min(candidates, key=lambda item: self.cost(item[0]))
                keyframe = painted is None
        if keyframe:
            self.keyframes += 1
            self.last_keyframe = self.frames
        else:
            self.delta_frames += 1
        if duplicate:
            self.repeated_frames += 1
        else:
            self.stored_frames += 1
            self.gap = gap
            if painted is None:
                self.previous = rgb.copy()
            else:
                self.previous = np.where(painted[:, :, None], rgb, self.previous).astype(np.uint8)
        self.frames += 1
        self.full_bytes += len(full)
        self.output_bytes += len(data)
        return data

    def finish(self):
        if not self.frames or self.mode == 'stream':
            return b''
        # Load all frames before starting, preserving timing even on a slow transport.
        placement = command(dict(a='p', i=self.image_id, p=1, C=1, q=2))
        return b'\x1b[H' + placement + self.control(c=1, s=3, v=self.loops + 1)

    def close(self):
        pass
