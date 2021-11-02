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
#
# This script is just a "wrapper" for all other tests in the folder.
# The script accepts a package type, so it can run an appropriate test for the package.
#
import json
import os
import pathlib as pl
import argparse
import shlex
import shutil
import subprocess
import sys
import logging
import tempfile

from typing import Union

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")


_PARENT_DIR = pl.Path(__file__).parent.absolute().resolve()
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent

# Add the source root to the PYTHONPATH. Since this is a script,this is required in order to be able to
# import inner modules.
sys.path.append(str(__SOURCE_ROOT__))

# Import internal modules only after the PYTHONPATH is tweaked.
from tests.package_tests import k8s_test, docker_test, package_test
from tests.package_tests import packages_sanity_tests
from agent_build.environment_deployers import deployers
from agent_build import package_builders


UBUNTU_1404 = "ubuntu-1404"
UBUNTU_1604 = "ubuntu-1604"
UBUNTU_1804 = "ubuntu-1804"
UBUNTU_2004 = "ubuntu-2004"
CENTOS_7 = "centos-7"
CENTOS_8 = "centos-8"
AMAZONLINUX_2 = "amazonlinux-2"
DOCKER_JSON = "docker-json"

TARGET_SYSTEM_TO_DOCKER_IMAGE = {
    UBUNTU_1404: "ubuntu:14.04",
    UBUNTU_1604: "ubuntu:16.04",
    UBUNTU_1804: "ubuntu:18.04",
    UBUNTU_2004: "ubuntu:20.04",
    CENTOS_7: "centos:7",
    CENTOS_8: "centos:8",
    AMAZONLINUX_2: "amazonlinux:2"
}

TARGET_SYSTEM_TO_EC2_AMI_DISTRO = {
    UBUNTU_1404: "ubuntu1404",
    UBUNTU_1604: "ubuntu1604",
    UBUNTU_1804: "ubuntu1804",
    UBUNTU_2004: "ubuntu2004",
    CENTOS_7: "centos7",
    CENTOS_8: "centos8",
    AMAZONLINUX_2: "amazonlinux2"
}

TARGET_SYSTEM_TO_PACKAGE_TYPE = {
    UBUNTU_1404: "deb",
    UBUNTU_1604: "deb",
    UBUNTU_1804: "deb",
    UBUNTU_2004: "deb",
    CENTOS_7: "rpm",
    CENTOS_8: "rpm",
    AMAZONLINUX_2: "rpm",
    DOCKER_JSON: "docker-json"
}

parser = argparse.ArgumentParser()

subparsers = parser.add_subparsers(dest="command")

test_parser = subparsers.add_parser("test")
get_info_parser = subparsers.add_parser("get")

for p in [test_parser, get_info_parser]:
    p.add_argument("target")

get_info_parser.add_argument("package-type")



test_parser.add_argument("--build-dir-path", dest="build_dir_path", required=False)

test_parser.add_argument("--package-path", required=False)
test_parser.add_argument("--frozen-test-runner-path", dest="frozen_test_runner_path")
test_parser.add_argument("--build-missing", dest="build_missing", action="store_true")

test_parser.add_argument("--where", required=False)
test_parser.add_argument("--in-docker", action="store_true")
test_parser.add_argument("--in_ec2", action="store_true")
test_parser.add_argument("--scalyr-api-key", required=False)


args = parser.parse_args()

config_path = pl.Path(__file__).parent / "credentials.json"

if config_path.exists():
    config = json.loads(config_path.read_text())
else:
    config = {}


def get_option(name: str, default: str = None, type_=str, ):
    global args
    global config

    name = name.lower()
    value = getattr(args, name, None)
    if value:
        return value

    value = os.environ.get(name.upper(), None)
    if value:
        if type_ == list:
            value = value.split(",")
        else:
            value = type_(value)
        return value

    value = config.get(name, None)
    if value:
        return value

    if default:
        return default

    raise ValueError(f"Can't find config option '{name}'")


target = args.target

package_type = TARGET_SYSTEM_TO_PACKAGE_TYPE[target]

if args.command == "get":
    print(package_type)
    exit(0)


package_build_spec = package_builders.PACKAGE_TYPES_TO_BUILD_SPECS[package_type]

if args.build_dir_path:
    build_dir_path = pl.Path(args.build_dir_path)
else:
    tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-package-test-")
    build_dir_path = pl.Path(tmp_dir.name)

# Build package if it is not specified and build-missing option is enabled.
if not args.package_path:
    if args.build_missing:
        package_output_path = build_dir_path / "package"
        if package_output_path.exists():
            shutil.rmtree(package_output_path)

        package_output_path.mkdir(parents=True)

        package_builders.build_package(
            package_type=package_type,
            package_build_spec=package_build_spec,
            output_path=package_output_path
        )

        filename_glob = package_build_spec.filename_glob
        found_files = list(package_output_path.glob(filename_glob))

        if len(found_files) != 1:
            raise FileNotFoundError(
                f"Can not find built package in the '{package_output_path}' directory with glob '{filename_glob}'"
            )

        package_path = found_files[0]
    else:
        raise ValueError("Option --package-path is required if it is not used with --build-missing")
else:
    package_path = pl.Path(args.package_path)

scalyr_api_key = get_option("scalyr_api_key")

frozen_test_runner_path = None

# If test has to run in docker or ec2, then the frozen test runner is required.
# Build it if it is not specified and build-missing option is set.
if args.where in ["docker", "ec2"]:
    if not args.frozen_test_runner_path and args.build_missing:
        frozen_binary_output_path = build_dir_path / "test_runner_frozen_binary"
        if frozen_binary_output_path.exists():
            shutil.rmtree(frozen_binary_output_path)

        frozen_binary_output_path.mkdir(parents=True)

        package_builders.build_test_runner_frozen_binary(
            package_type=package_type,
            package_build_spec=package_build_spec,
            output_path=frozen_binary_output_path,

        )

        filename = pl.Path(__file__).stem
        frozen_test_runner_path = list(frozen_binary_output_path.glob(f"{filename}*"))[0]
    else:
        frozen_test_runner_path = pl.Path(args.frozen_test_runner_path)


if args.where == "docker":
    docker_image = TARGET_SYSTEM_TO_DOCKER_IMAGE.get(target)
    if not docker_image:
        raise ValueError(f"Can not find docker image for operation system '{target}'")

    if not frozen_test_runner_path:
        raise ValueError(
            "Option --frozen-test-runner-path is required with --where=='docker' and if it is not used with --build-missing"
        )

    executable_mapping_args = ["-v", f"{frozen_test_runner_path}:/tmp/test_executable"]
    test_executable_path = "/tmp/test_executable"

    # Run the test inside the docker.
    # fmt: off
    subprocess.check_call(
        [
            "docker", "run", "-i", "--rm", "--init",
            "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
            "-v", f"{package_path}:/tmp/package",
            *executable_mapping_args,
            # specify the image.
            docker_image,
            # Command to run the test executable inside the container.
            test_executable_path,
            "test",
            target,
            "--package-path", f"/tmp/package", "--scalyr-api-key", scalyr_api_key
        ]
    )
    # fmt: on
    exit(0)
elif args.where == "ec2":
    aws_access_key = get_option("aws_access_key")
    aws_secret_key = get_option("aws_secret_key")
    aws_keypair_name = get_option("aws_keypair_name")
    aws_private_key_path = get_option("aws_private_key_path")
    aws_security_groups = get_option("aws_security_groups")
    aws_region = get_option("aws_region", "us-east-1")
    scalyr_api_key = get_option("scalyr_api_key")

    ami_image = TARGET_SYSTEM_TO_EC2_AMI_DISTRO.get(target)
    if not ami_image:
        raise ValueError(f"Can not find AMI image for the operation system '{target}'")

    if not frozen_test_runner_path:
        raise ValueError(
            "Option --frozen-test-runner-path is required with --where=='ec2' and if it is not used with --build-missing"
        )

    def create_command(test_runner_path_remote_path: str, package_remote_path: str):
        command = [
            test_runner_path_remote_path,
            "test",
            target,
            "--package-path",
            package_remote_path,
            "--scalyr-api-key",
            scalyr_api_key
        ]
        return shlex.join(command)

    packages_sanity_tests.main(
        distro=ami_image,
        to_version=str(package_path),
        create_remote_test_command=create_command,
        test_runner_path=frozen_test_runner_path,
        access_key=aws_access_key,
        secret_key=aws_secret_key,
        keypair_name=aws_keypair_name,
        private_key_path=aws_private_key_path,
        security_groups=aws_security_groups,
        region=aws_region,
        destroy_node=True
    )
else:

    if package_type in ["deb", "rpm", "msi", "tar"]:
        package_test.run(
            package_path=package_path,
            package_type=package_type,
            scalyr_api_key=scalyr_api_key
        )
    elif package_type == "k8s":
        k8s_test.run(
            builder_path=package_path,
            scalyr_api_key=scalyr_api_key
        )
    elif package_type in ["docker-json"]:
        docker_test.run(
            builder_path=package_path,
            scalyr_api_key=scalyr_api_key
        )
    else:
        raise ValueError(f"Wrong package type - {package_type}")