import os

from setuptools import Extension, setup

extensions = []
if os.environ.get("SIXEL_VIDEO_BUILD_CYTHON") == "1":
    from Cython.Build import cythonize

    extensions = cythonize(
        [Extension("sixel_video._delta", ["src/sixel_video/_delta.pyx"])],
        build_dir="build/cython",
        compiler_directives={"language_level": 3},
    )

setup(ext_modules=extensions)
