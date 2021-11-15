import io
import logging
import subprocess
import sys
from typing import Union
import pathlib as pl


DEFAULT_LINES_NUMBER_TO_SHOW_ON_ERROR = 100


def quiet_subprocess_call(
        cmd,
        *args,
        number_of_lines_to_show: int = 0,
        number_of_lines_on_error: int = 100,
        **kwargs
):
    stdout = kwargs.pop("stdout", subprocess.PIPE)
    stderr = kwargs.pop("stderr", subprocess.STDOUT)


    process = subprocess.Popen(
        cmd,
        *args,
        stdout=stdout,
        stderr=stderr,
        ** kwargs
    )

    lines = []

    if number_of_lines_to_show >= 0:
        for line in process.stdout.readlines():
            lines.append(line)

    process.wait()

    last_lines = []

    if process.returncode != 0:
        last_lines = lines[-number_of_lines_on_error:]
    else:
        if number_of_lines_to_show !=0:
            last_lines = lines[-number_of_lines_to_show:]

    result_output = b"".join(last_lines).decode()

    if result_output:
        print(result_output, flush=True, file=sys.stderr)


    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            returncode=process.returncode,
            cmd=cmd
        )



