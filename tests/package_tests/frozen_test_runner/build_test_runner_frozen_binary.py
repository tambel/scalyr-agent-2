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
from agent_tools import environment_deployments
from tests.package_tests import current_test_specifications

def build_test_runner_frozen_binary(
        output_path: pl.Path,
        filename: str,
        deployment_name: str,
        locally: bool = False
):
    deployment = environment_deployments.Deployment.ALL_DEPLOYMENTS[deployment_name]

    if locally or not deployment.in_docker:
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
        # "--architecture",
        # deployment.architecture.value,
        "--filename",
        filename,
        # "--base-image-name",
        # deployment.result_image_name,
        "--deployment-name",
        deployment_name,
        "--output-dir",
        "/tmp/build",
        "--locally"
    ]

    command = shlex.join(command_args)

    image_name = f"agent-package-frozen-binary-builder-{deployment.result_image_name}"

    build_in_docker.build_stage(
        command=command,
        stage_name="test",
        architecture=deployment.architecture,
        image_name=image_name,
        base_image_name=deployment.result_image_name,
        output_path=output_path
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--locally", required=False, action="store_true")
    parser.add_argument("--deployment-name", required=True)

    args = parser.parse_args()

    build_test_runner_frozen_binary(
        output_path=pl.Path(args.output_dir),
        filename=args.filename,
        deployment_name=args.deployment_name,
        locally=args.locally
    )