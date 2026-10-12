"""Small independent interpreter for the emitted Kitty animation commands."""

import base64
import re
import zlib

import cv2
import numpy as np


def commands(data):
    pending = None
    payload = bytearray()
    for match in re.finditer(rb'\x1b_G([^;]*);([^\x1b]*)\x1b\\', data):
        header = dict(item.split('=', 1) for item in match[1].decode().split(',') if item)
        assert len(match[2]) <= 4096
        assert len(match[2]) % 4 == 0
        if pending is None:
            pending = header
        else:
            assert set(header) <= {'a', 'm', 'q'}
            if pending.get('a') == 'f':
                assert header.get('a') == 'f'
        payload.extend(match[2])
        if header.get('m', '0') == '0':
            yield pending, base64.b64decode(payload, validate=True)
            pending, payload = None, bytearray()
    assert pending is None, 'Incomplete chunked image'


def decode(data):
    frames, gaps, controls = [], [], []
    for header, payload in commands(data):
        action = header.get('a', 't')
        if action in ('t', 'T', 'f'):
            if header.get('o') == 'z':
                payload = zlib.decompress(payload)
            fmt = int(header['f'])
            if fmt == 100:
                pixels = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_UNCHANGED)
                pixels = pixels[:, :, [2, 1, 0, 3] if pixels.shape[2] == 4 else [2, 1, 0]]
            else:
                pixels = np.frombuffer(payload, np.uint8).reshape(int(header['v']), int(header['s']), fmt // 8)
            if action in ('t', 'T'):
                frames.append(pixels[:, :, :3].copy())
                gaps.append(0)
                continue
            canvas = frames[int(header['c']) - 1].copy() if 'c' in header else np.zeros_like(frames[0])
            x, y = int(header.get('x', 0)), int(header.get('y', 0))
            h, w = pixels.shape[:2]
            assert x + w <= canvas.shape[1] and y + h <= canvas.shape[0]
            region = canvas[y:y + h, x:x + w]
            if pixels.shape[2] == 4 and header.get('X', '0') == '0':
                assert np.isin(pixels[:, :, 3], [0, 255]).all()
                painted = pixels[:, :, 3] == 255
                region[painted] = pixels[:, :, :3][painted]
            else:
                region[:] = pixels[:, :, :3]
            frames.append(canvas)
            gaps.append(int(header.get('z', 40)))
        elif action == 'a':
            if 'r' in header and 'z' in header:
                gaps[int(header['r']) - 1] = int(header['z'])
            controls.append(header)
    return frames, gaps, controls
