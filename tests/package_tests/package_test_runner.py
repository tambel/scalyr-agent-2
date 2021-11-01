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

import pathlib as pl
import argparse
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")


_PARENT_DIR = pl.Path(__file__).parent.absolute().resolve()
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent

# Add the source root to the PYTHONPATH. Since this is a script,this is required in order to be able to
# import inner modules.
sys.path.append(str(__SOURCE_ROOT__))

# Import internal modules only after the PYTHONPATH is tweaked.
from tests.package_tests import k8s_test, docker_test, package_test
from tests.package_tests import packages_sanity_tests


UBUNTU_1404 = "ubuntu-1404"
UBUNTU_1604 = "ubuntu-1604"
UBUNTU_1804 = "ubuntu-1804"
UBUNTU_2004 = "ubuntu-2004"
CENTOS_7 = "centos-7"
CENTOS_8 = "centos-8"
DOCKER_JSON = "docker-json"

OS_TO_DOCKER_IMAGE = {
    UBUNTU_1404: "ubuntu:14.04",
    UBUNTU_1604: "ubuntu:16.04",
    UBUNTU_1804: "ubuntu:18.04",
    UBUNTU_2004: "ubuntu:20.04",
    CENTOS_7: "centos:7",
    CENTOS_8: "centos:8",
}

OS_TO_EC2_AMI_DISTRO = {
    UBUNTU_1404: "ubuntu-1404",
    UBUNTU_1604: "ubuntu-1604",
    UBUNTU_1804: "ubuntu-1804",
    UBUNTU_2004: "ubuntu-2004",
    CENTOS_7: "centos-7",
    CENTOS_8: "centos-8",
}

OS_TO_PACKAGE_TYPE = {
    UBUNTU_1404: "deb",
    UBUNTU_1604: "deb",
    UBUNTU_1804: "deb",
    UBUNTU_2004: "deb",
    CENTOS_7: "rpm",
    CENTOS_8: "rpm",
    DOCKER_JSON: "docker-json"
}


parser = argparse.ArgumentParser()

parser.add_argument("target")

subparsers = parser.add_subparsers(dest="command")

test_parser = subparsers.add_parser("test")
get_info_parser = subparsers.add_parser("get")
get_info_parser.add_argument("package-type")

test_parser.add_argument("--package-path", required=True)
#test_parser.add_argument("--package-type", required=True)
test_parser.add_argument("--where", required=False)
test_parser.add_argument("--package-test-path")
test_parser.add_argument("--in-docker", action="store_true")
test_parser.add_argument("--in_ec2", action="store_true")
test_parser.add_argument("--scalyr-api-key", required=True)


args = parser.parse_args()

target = args.target

package_type = OS_TO_PACKAGE_TYPE[target]

if args.command == "get":
    print(package_type)
    exit(0)


package_path = pl.Path(args.package_path)

if args.package_test_path:
    package_test_path = pl.Path(args.package_test_path)


if args.where == "docker":
    docker_image = OS_TO_DOCKER_IMAGE.get(args.os)
    if not docker_image:
        raise ValueError(f"Can not find docker image for operation system '{args.os}'")

    if args.package_test_path:
        executable_mapping_args = ["-v", f"{args.package_test_path}:/tmp/test_executable"]
        test_executable_path = "/tmp/test_executable"
    else:
        executable_mapping_args = []
        test_executable_path = "/scalyr-agent-2/tests/package_tests/package_test_runner.py"

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
            "--package-path", f"/tmp/package", "--scalyr-api-key", args.scalyr_api_key
        ]
    )
    # fmt: on
    exit(0)
elif args.where == "ec2":
    ami_image = OS_TO_EC2_AMI_DISTRO.get(args.os)
    if not ami_image:
        raise ValueError(f"Can not find AMI image for the operation system '{args.os}'")

    packages_sanity_tests.main(
        distro=ami_image,
        to_version=str(package_path)
    )
else:

    if package_type in ["deb", "rpm", "msi", "tar"]:
        package_test.run(
            package_path=package_path,
            package_type=package_type,
            scalyr_api_key=args.scalyr_api_key
        )
    elif package_type == "k8s":
        k8s_test.run(
            builder_path=package_path,
            scalyr_api_key=args.scalyr_api_key
        )
    elif package_type in ["docker-json"]:
        docker_test.run(
            builder_path=package_path,
            scalyr_api_key=args.scalyr_api_key
        )
    else:
        raise ValueError(f"Wrong package type - {package_type}")