import argparse
import pathlib as pl
import sys
import subprocess
import os
import stat
import shlex

_PARENT_DIR = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.parent

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import constants
from agent_tools import build_in_docker

def build_test_runner_frozen_binary(
        output_path: pl.Path,
        filename: str,
        architecture: constants.Architecture,
        base_image_name: str = None,
        locally: bool = False
):
    if locally or not base_image_name:
        agent_tools_path = __SOURCE_ROOT__ / "agent_tools"
        main_script_path = _PARENT_DIR / "frozen_test_runner_main.py"

        build_path = output_path / "build"
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                str(main_script_path),
                "--add-data",
                f"{agent_tools_path}{os.path.pathsep}agent_tools",
                "--paths",
                "tests",
                "--hidden-import",
                "tests.package_tests",
                "--distpath",
                str(output_path),
                "--workpath",
                str(build_path),
                "-n",
                filename,
                "--onefile",
            ],
            cwd=__SOURCE_ROOT__
        )

        # Make the package test frozen binaries executable.
        for child_path in output_path.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        return

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"


    build_frozen_binary_script_path = "/scalyr-agent-2/tests/package_tests/frozen_test_runner/build_test_runner_frozen_binary.py"

    command_args = [
        "python3",
        str(build_frozen_binary_script_path),
        "--architecture",
        architecture.value,
        "--filename",
        filename,
        "--base-image-name",
        base_image_name,
        "--output-dir",
        "/tmp/build",
        "--locally"
    ]

    command = shlex.join(command_args)

    image_name = f"agent-package-frozen-binary-builder-{base_image_name}"

    build_in_docker.build_stage(
        command=command,
        stage_name="test",
        architecture=architecture,
        image_name=image_name,
        base_image_name=base_image_name,
        output_path=output_path
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--base-image-name", required=False)
    parser.add_argument("--locally", required=False, action="store_true")

    args = parser.parse_args()

    build_test_runner_frozen_binary(
        output_path=pl.Path(args.output_dir),
        filename=args.filename,
        architecture=constants.Architecture(args.architecture),
        base_image_name=args.base_image_name,
        locally=args.locally
    )