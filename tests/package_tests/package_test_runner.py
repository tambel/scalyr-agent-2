import argparse
import collections
import dataclasses
import enum
import json
import pathlib as pl
import subprocess
import tempfile
import shutil
import logging
import sys
import stat
import shlex
import os

from typing import List, Union, Dict


__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(__SOURCE_ROOT__))


from agent_build.environment_deployers import deployers
from agent_build import package_builders
from tests.package_tests import deb_rpm_tar_msi_test
from tests.package_tests import packages_sanity_tests

__frozen__ = hasattr(sys, "frozen")

class DockerImages(enum.Enum):
    UBUNTU_1404 = "ubuntu:14.04"
    UBUNTU_1604 = "ubuntu:16.04"


@dataclasses.dataclass
class DockerBasedTestSpec:
    image_name: str


class TargetSystem(enum.Enum):
    UBUNTU_1404 = "ubuntu-1404"


@dataclasses.dataclass
class PackageTestSpec:
    target_system: TargetSystem
    package_builder_spec: package_builders.PackageBuildSpec
    remote_machine_spec: Union[DockerBasedTestSpec, packages_sanity_tests.Ec2BasedTestSpec] = None


SPECS: Dict[str, PackageTestSpec] = {}
PACKAGE_BUILDER_TO_TEST_SPEC: Dict[str, List[PackageTestSpec]] = collections.defaultdict(list)


def create_test_spec(
        target_system: TargetSystem,
        package_builder_spec: package_builders.PackageBuildSpec,
        remote_machine_specs: List[Union[DockerBasedTestSpec, packages_sanity_tests.Ec2BasedTestSpec]] = None
):

    global SPECS, PACKAGE_BUILDER_TO_TEST_SPEC

    package_build_spec_name = package_builders.create_build_spec_name(
        package_type=package_builder_spec.package_type,
        architecture=package_builder_spec.architecture
    )
    test_spec_name = f"{target_system.value}_{package_builder_spec.base_image.architecture.value}"
    if remote_machine_specs:
        for remote_machine_spec in remote_machine_specs:
            if isinstance(remote_machine_spec, DockerBasedTestSpec):
                remote_machine_suffix = "docker"
            elif isinstance(remote_machine_spec, packages_sanity_tests.Ec2BasedTestSpec):
                remote_machine_suffix = "ec2"
            else:
                raise ValueError(f"Wrong remote machine spec: {remote_machine_spec}")

            full_name = f"{test_spec_name}_{remote_machine_suffix}"

            spec = PackageTestSpec(
                target_system=target_system,
                package_builder_spec=package_builder_spec,
                remote_machine_spec=remote_machine_spec
            )
            SPECS[full_name] = spec
            PACKAGE_BUILDER_TO_TEST_SPEC[package_build_spec_name].append(spec)
    else:
        spec = PackageTestSpec(
            target_system=target_system,
            package_builder_spec=package_builder_spec,
        )

        SPECS[test_spec_name] = spec
        PACKAGE_BUILDER_TO_TEST_SPEC[package_build_spec_name].append(spec)


create_test_spec(
    target_system=TargetSystem.UBUNTU_1404,
    package_builder_spec=package_builders.DEB_x86_64,
    remote_machine_specs=[
        DockerBasedTestSpec("ubuntu:14.04"),
        packages_sanity_tests.Ec2BasedTestSpec(
            image_name="Ubuntu Server 14.04 LTS (HVM)",
            image_id="ami-07957d39ebba800d5",
            size_id="t2.small",
            ssh_username="ubuntu",
            os_family=packages_sanity_tests.OSFamily.LINUX
        )
    ],
)
create_test_spec(
    target_system=TargetSystem.UBUNTU_1404,
    package_builder_spec=package_builders.DEB_ARM64,
    remote_machine_specs=[
        DockerBasedTestSpec("ubuntu:14.04"),
        packages_sanity_tests.Ec2BasedTestSpec(
            image_name="Ubuntu Server 14.04 LTS (HVM)",
            image_id="ami-07957d39ebba800d5",
            size_id="t2.small",
            ssh_username="ubuntu",
            os_family=packages_sanity_tests.OSFamily.LINUX
        )
    ],
)


def run_test_from_docker(
    target_spec_name: str,
    package_path: pl.Path,
    frozen_test_runner_path: pl.Path,
    docker_image: str,
    architecture: deployers.Architecture,
    scalyr_api_key: str
):

    # Run the test inside the docker.
    # fmt: off
    subprocess.check_call(
        [
            "docker", "run", "-i", "--rm", "--init",
            "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
            "-v", f"{package_path}:/tmp/package",
            "-v", f"{frozen_test_runner_path}:/tmp/test_executable",
            "--platform",
            deployers.architecture_to_docker_architecture(architecture),
            # specify the image.
            docker_image,
            # Command to run the test executable inside the container.
            "/tmp/test_executable",
            "run",
            target_spec_name,
            "--package-path", f"/tmp/package",
            "--locally",
            "--scalyr-api-key", scalyr_api_key
        ]
    )
    # fmt: on


def run_test_in_ec2_instance(
        test_spec_name: str,
        package_path: pl.Path,
        frozen_test_runner_path: pl.Path,
        scalyr_api_key: str
):
    from tests.package_tests import packages_sanity_tests

    test_spec = SPECS[test_spec_name]


    aws_access_key = get_option("aws_access_key")
    aws_secret_key = get_option("aws_secret_key")
    aws_keypair_name = get_option("aws_keypair_name")
    aws_private_key_path = get_option("aws_private_key_path")
    aws_security_groups = get_option("aws_security_groups")
    aws_region = get_option("aws_region", "us-east-1")
    scalyr_api_key = get_option("scalyr_api_key")

    ami_image: packages_sanity_tests.Ec2BasedTestSpec = test_spec.remote_machine_spec

    def create_command(test_runner_path_remote_path: str, package_remote_path: str):
        command = [
            test_runner_path_remote_path,
            "run",
            test_spec_name,
            "--package-path",
            package_remote_path,
            "--scalyr-api-key",
            scalyr_api_key,
            "--locally"
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


def build_test_runner_frozen_binary(
        test_spec_name: str,
        output_path: Union[str, pl.Path],
        locally: bool = False,
):
    # Also build the frozen binary for the package test script, they will be used to test the packages later.

    output_path = pl.Path(output_path)
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    test_spec = SPECS[test_spec_name]
    package_build_spec = test_spec.package_builder_spec

    if locally or not package_build_spec.base_image:
        package_test_script_path = pl.Path(__file__).absolute()

        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                str(package_test_script_path),
                "--distpath",
                str(output_path),
                "--onefile",
            ]
        )

        # Make the package test frozen binaries executable.
        for child_path in output_path.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    else:

        build_package_script_path = pl.Path("/scalyr-agent-2/tests/package_tests/package_test_runner.py")
        command_argv = [
            str(build_package_script_path),
            "build-frozen-test-runner",
            test_spec_name,
            "--locally",
            "--output-dir",
            "/tmp/build",
        ]

        command = shlex.join(command_argv)

        package_builders.run_command_in_docker_and_get_output(
            package_build_spec=package_build_spec,
            command=command,
            output_path=output_path,
            build_stage="test"
        )


def _prepare_build_dir(path: Union[str, pl.Path] = None):
    if path:
        return pl.Path(path)
    else:
        tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-package-test-")
        return pl.Path(tmp_dir.name)


def run_test_from_spec(
        test_spec_name: str,
        scalyr_api_key: str,
        package_path: str,
        build_dir_path: str = None,
        locally: bool = False,
):
    test_spec = SPECS[test_spec_name]

    if not package_path:
        if __frozen__:
            raise ValueError("Package path has to be specified in frozen test runner.")

        build_dir_path = _prepare_build_dir(build_dir_path)

        package_output_dir_path = build_dir_path / "package"

        package_builders.build_package(
            package_build_spec=test_spec.package_builder_spec,
            output_path=package_output_dir_path
        )
        final_package_path = list(package_output_dir_path.glob(test_spec.package_builder_spec.filename_glob))[0]
    else:
        final_package_path = pl.Path(package_path)

    spec = SPECS[test_spec_name]

    if locally or not spec.remote_machine_spec:
        if spec.package_builder_spec.package_type in [
            package_builders.PackageType.DEB,
            package_builders.PackageType.RPM,
            package_builders.PackageType.TAR,
            package_builders.PackageType.MSI
        ]:
            deb_rpm_tar_msi_test.run(
                package_path=final_package_path,
                package_type=spec.package_builder_spec.package_type,
                scalyr_api_key=scalyr_api_key
            )
            return

    build_dir_path = _prepare_build_dir(build_dir_path)
    frozen_test_runner_output_dir_path = build_dir_path / "frozen_test_runner"

    build_test_runner_frozen_binary(
        test_spec_name=args.spec_name,
        output_path=frozen_test_runner_output_dir_path,
    )

    script_filename = pl.Path(__file__).stem
    frozen_test_runner_path = list(frozen_test_runner_output_dir_path.glob(f"{script_filename}*"))[0]

    if isinstance(spec.remote_machine_spec, DockerBasedTestSpec):
        run_test_from_docker(
            target_spec_name=test_spec_name,
            package_path=final_package_path,
            frozen_test_runner_path=frozen_test_runner_path,
            docker_image=spec.remote_machine_spec.image_name,
            architecture=spec.package_builder_spec.architecture,
            scalyr_api_key=scalyr_api_key
        )
        return

    if isinstance(spec.remote_machine_spec, packages_sanity_tests.Ec2BasedTestSpec):
        run_test_in_ec2_instance(
            test_spec_name=test_spec_name,
            package_path=final_package_path,
            frozen_test_runner_path=frozen_test_runner_path,
            scalyr_api_key=scalyr_api_key
        )


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


def main():
    pass


if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    run_test_parser = subparsers.add_parser("run")
    run_test_parser.add_argument("spec_name", choices=SPECS.keys())
    run_test_parser.add_argument("--package-path", dest="package_path", required=False)
    run_test_parser.add_argument("--scalyr-api-key", dest="scalyr_api_key", required=False)
    run_test_parser.add_argument("--locally", required=False, action="store_true")
    run_test_parser.add_argument("--build-dir-path", dest="build_dir_path")
    run_test_parser.add_argument("--frozen-test-runner-path", dest="frozen_test_runner_path", required=False)

    build_frozen_test_runner = subparsers.add_parser("build-frozen-test-runner")
    build_frozen_test_runner.add_argument("spec_name", choices=SPECS.keys())
    build_frozen_test_runner.add_argument("--output-dir", dest="output_dir")
    build_frozen_test_runner.add_argument("--locally", required=False, action="store_true")

    spec_info_parser = subparsers.add_parser("get-test-specs")
    spec_info_parser.add_argument("package_type", choices=package_builders.SPECS.keys())

    args = parser.parse_args()

    if args.command == "run":
        run_test_from_spec(
            test_spec_name=args.spec_name,
            package_path=args.package_path,
            scalyr_api_key=get_option("scalyr_api_key"),
            build_dir_path=args.build_dir_path,
            locally=args.locally
        )
        sys.exit(0)

    if args.command == "build-frozen-test-runner":
        spec = SPECS[args.spec_name]

        build_test_runner_frozen_binary(
            test_spec_name=args.spec_name,
            output_path=pl.Path(args.output_dir),
            locally=args.locally
        )
        sys.exit(0)

    if args.command == "get-test-specs":

        test_specs = PACKAGE_BUILDER_TO_TEST_SPEC[args.package_type]

        result_json_specs = []
        for spec in test_specs:
            json_result = {}
            used_deployer_names = [d.name for d in spec.package_builder_spec.used_deployers]
            used_deployers_str = ",".join(used_deployer_names)

            json_result["deployers"] = used_deployers_str
            json_result["base-docker-image"] = spec.package_builder_spec.base_image.image_name
            json_result["architecture"] = spec.package_builder_spec.architecture.value

            result_json_specs.append(json_result)

            print(json.dumps(result_json_specs))

        sys.exit(0)









a=10