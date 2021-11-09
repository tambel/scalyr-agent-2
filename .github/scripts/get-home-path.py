import pathlib

cache_path = pathlib.Path.home() / "build-caches"

print(str(cache_path.absolute()).replace("\\", "\\\\"))

