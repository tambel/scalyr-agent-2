# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This script build frozen binary for the package test runner. The frozen package test runner is needed to run package
tests on real "clean" machines, for example on AWS Ec2, or docker without any preliminary work
"""


import argparse
import pathlib as pl
import sys
import subprocess
import os
import stat
import shlex
import logging

_PARENT_DIR = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.parent

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import build_in_docker
from agent_tools.environment_deployments import deployments
import tests.package_tests


def build_test_runner_frozen_binary(
        output_path: pl.Path,
        filename: str,
        deployment_name: str,
        locally: bool = False
):
    """
    Build the frozen binary of the test runner script by using PyInstaller library. Can also build it inside docker.
    :param output_path: Output directory path.
    :param filename: Name of the result file,
    :param deployment_name: Name of the environment deployment which is required to build the frozen binary.
    :param locally: If True build on current system, otherwise in docker.
    """
    deployment = deployments.ALL_DEPLOYMENTS[deployment_name]

    if locally or not deployment.in_docker:
        agent_tools_path = __SOURCE_ROOT__ / "agent_tools"
        main_script_path = _PARENT_DIR / "frozen_test_runner_main.py"

        main_script_path= main_script_path.absolute()

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

    # Build frozen binary inside the docker. To do that run the same script in docker again.
    docker_side_source_path = pl.Path("/scalyr-agent-2")

    docker_side_build_script_path = docker_side_source_path / pl.Path(__file__).absolute().relative_to(__SOURCE_ROOT__)

    command_args = [
        "python3",
        str(docker_side_build_script_path),
        "--filename",
        filename,
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
        output_path_mappings={output_path: pl.Path("/tmp/build")}
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

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