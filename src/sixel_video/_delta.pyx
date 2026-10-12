# cython: boundscheck=False, wraparound=False
"""Optional exact RGB comparison using contiguous typed memoryviews."""

import numpy as np
from libc.stdlib cimport abs


def changed_mask(const unsigned char[:, :, ::1] current,
                 const unsigned char[:, :, ::1] previous, int threshold=0):
    cdef Py_ssize_t height = current.shape[0]
    cdef Py_ssize_t width = current.shape[1]
    cdef Py_ssize_t y, x
    if threshold < 0 or threshold > 100:
        raise ValueError("Threshold must be from 0 to 100 percentage points")
    if (current.shape[2] != 3 or previous.shape[2] != 3
            or previous.shape[0] != height or previous.shape[1] != width):
        raise ValueError("RGB images must have matching shapes")
    result = np.empty((height, width), dtype=np.uint8)
    cdef unsigned char[:, ::1] mask = result
    with nogil:
        for y in range(height):
            for x in range(width):
                mask[y, x] = (abs(<int>current[y, x, 0] - <int>previous[y, x, 0]) > threshold
                              or abs(<int>current[y, x, 1] - <int>previous[y, x, 1]) > threshold
                              or abs(<int>current[y, x, 2] - <int>previous[y, x, 2]) > threshold)
    return result.view(np.bool_)
