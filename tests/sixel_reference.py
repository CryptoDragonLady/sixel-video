"""A small independent sixel interpreter for reconstruction assertions."""

import re

import numpy as np


def decode(frame, previous=None):
    header = re.match(rb'\x1b\[H\x1bP([0-9;]*)q', frame)
    assert header and frame.endswith(b'\x1b\\\n'), 'Invalid frame envelope'
    parameters = header[1].split(b';')
    transparent = len(parameters) > 1 and parameters[1] == b'1'
    body = frame[header.end():-3].decode('ascii')
    raster = re.match(r'"1;1;(\d+);(\d+)', body)
    assert raster, 'Missing raster size'
    width, height = int(raster[1]), int(raster[2])
    pixels = np.full((height, width), -1, dtype=np.int16)
    palette = {}
    x = y = color = 0
    position = raster.end()
    while position < len(body):
        char = body[position]
        if char == '#':
            token = re.match(r'#(\d+)(?:;2;(\d+);(\d+);(\d+))?', body[position:])
            assert token
            color = int(token[1])
            if token[2] is not None:
                palette[color] = tuple(int(v) for v in token.groups()[1:])
            position += token.end()
        elif char in '$-':
            x = 0
            y += 6 if char == '-' else 0
            position += 1
        else:
            count = 1
            if char == '!':
                token = re.match(r'!(\d+)', body[position:])
                count = int(token[1])
                position += token.end()
                char = body[position]
            mask = ord(char) - 63
            assert 0 <= mask <= 63 and x + count <= width and y < height
            for bit in range(6):
                if mask & (1 << bit) and y + bit < height:
                    pixels[y + bit, x:x + count] = color
            x += count
            position += 1
    if previous is None or not transparent:
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
    else:
        assert previous.shape == (height, width, 3)
        canvas = previous.copy()
    for color, channels in palette.items():
        canvas[pixels == color] = channels
    assert all(c in palette for c in np.unique(pixels[pixels >= 0]))
    return canvas, pixels >= 0
