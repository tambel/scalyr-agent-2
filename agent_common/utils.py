from typing import Union
import pathlib as pl

__all__ = ["find_file_in_dir_by_glob"]

def find_file_in_dir_by_glob(
    dir_path: Union[str, pl.Path],
    filename_glob: str,
) -> pl.Path:

    dir_path = pl.Path(dir_path)
    found_files = list(dir_path.glob(filename_glob))
    if len(found_files) > 1:
        raise ValueError(f"More than one file is found by using glob '{filename_glob}' in directory '{dir_path}'.")
    if not found_files:
        raise FileNotFoundError(f"Can not find any file by using glob '{filename_glob}' in directory '{dir_path}'.")

    return found_files[0]



