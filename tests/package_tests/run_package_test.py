import argparse
import json
import pathlib as pl
import logging
import sys
import os
import tempfile
import shutil
from typing import Union

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from tests.package_tests import current_test_specifications
from tests.package_tests.frozen_test_runner import build_test_runner_frozen_binary


_TEST_CONFIG_PATH = pl.Path(__file__).parent / "credentials.json"

if _TEST_CONFIG_PATH.exists():
    config = json.loads(_TEST_CONFIG_PATH.read_text())
else:
    config = {}


def get_option(name: str, default: str = None, type_=str, ):
    global config

    name = name.lower()

    env_variable_name = name.upper()
    value = os.environ.get(env_variable_name, None)
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

    raise ValueError(
        f"Can't find config option '{name}' "
        f"Provide it through '{env_variable_name}' env. variable or by "
        f"specifying it in the test config file - {_TEST_CONFIG_PATH}."
    )


def test_package(
        package_test_name: str,
        build_dir_path: pl.Path,
        scalyr_api_key: str,
        package_path: Union[str, pl.Path] = None,
        frozen_package_test_runner_path: Union[str, pl.Path] = None

,
):

    if not build_dir_path:
        build_dir_path = pl.Path(tempfile.mkdtemp())
    else:
        build_dir_path = pl.Path(build_dir_path)

    package_test = current_test_specifications.PackageTest.ALL_TESTS[package_test_name]

    if not package_path:
        package_output_dir_path = build_dir_path / "package"

        if package_output_dir_path.exists():
            shutil.rmtree(package_output_dir_path)
        package_output_dir_path.mkdir(parents=True)

        package_builder = package_test.package_builder

        package_builder.build(
            output_path=package_output_dir_path
        )
        package_path = list(
            package_output_dir_path.glob(package_test.package_builder.filename_glob)
        )[0]
    else:
        package_path = pl.Path(package_path)

    if isinstance(package_test, current_test_specifications.RemoteMachinePackageTest):

        if not frozen_package_test_runner_path:

            frozen_test_runner_build_dir_path = build_dir_path / "frozen_test_runner"
            if frozen_test_runner_build_dir_path.exists():
                shutil.rmtree(frozen_test_runner_build_dir_path)

            frozen_test_runner_build_dir_path.mkdir(parents=True)

            package_test.deployment.deploy()

            test_runner_filename = "frozen_test_runner"

            build_test_runner_frozen_binary.build_test_runner_frozen_binary(
                output_path=frozen_test_runner_build_dir_path,
                filename=test_runner_filename,
                deployment_name=package_test.deployment.name
            )

            frozen_package_test_runner_path = frozen_test_runner_build_dir_path / test_runner_filename
        else:
            frozen_package_test_runner_path = pl.Path(frozen_package_test_runner_path)

        if isinstance(package_test, current_test_specifications.DockerBasedPackageTest):
            package_test.run_in_docker(
                package_path=package_path,
                test_runner_frozen_binary_path=frozen_package_test_runner_path,
                scalyr_api_key=scalyr_api_key,
            )
        elif isinstance(package_test, current_test_specifications.Ec2BasedPackageTest):
            package_test.run_in_ec2(
                package_path=package_path,
                test_runner_frozen_binary_path=frozen_package_test_runner_path,
                scalyr_api_key=scalyr_api_key,
                aws_access_key=get_option("aws_access_key"),
                aws_secret_key = get_option("aws_secret_key"),
                aws_keypair_name = get_option("aws_keypair_name"),
                aws_private_key_path = get_option("aws_private_key_path"),
                aws_security_groups = get_option("aws_security_groups"),
                aws_region=get_option("aws_region", "us-east-1"),
            )
    else:
        package_test.run_test_locally(
            package_path=package_path,
            scalyr_api_key=scalyr_api_key
        )

    #
    # current_test_specifications.run_package_test(
    #     package_test_name=package_test_name,
    #     package_path=package_path,
    #     build_dir_path=build_dir_path,
    #     aws_access_key=get_option("aws_access_key"),
    #     aws_secret_key = get_option("aws_secret_key"),
    #     aws_keypair_name = get_option("aws_keypair_name"),
    #     aws_private_key_path = get_option("aws_private_key_path"),
    #     aws_security_groups = get_option("aws_security_groups"),
    #     aws_region=get_option("aws_region", "us-east-1"),
    #     scalyr_api_key=scalyr_api_key,
    # )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

    parser = argparse.ArgumentParser()

    parser.add_argument("test_name", choices=current_test_specifications.PackageTest.ALL_TESTS.keys())

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_test_parser = subparsers.add_parser("run")
    run_test_parser.add_argument("--build-dir-path", dest="build_dir_path", required=False)
    run_test_parser.add_argument("--package-path", dest="package_path", required=False)
    run_test_parser.add_argument(
        "--frozen-package-test-runner-path",
        dest="frozen_package_test_runner_path",
        required=False
    )
    run_test_parser.add_argument("--scalyr-api-key", dest="scalyr_api_key", required=False)

    get_deployment_name_parser = subparsers.add_parser("get-deployment-name")

    args = parser.parse_args()

    if args.command == "run":
        test_package(
            package_test_name=args.test_name,
            build_dir_path=args.build_dir_path,
            package_path=args.package_path,
            scalyr_api_key=get_option("scalyr_api_key", args.scalyr_api_key),
            frozen_package_test_runner_path=args.frozen_package_test_runner_path

        )
        exit(0)

    if args.command == "get-deployment-name":
        package_test = current_test_specifications.PackageTest.ALL_TESTS[args.test_name]

        package_test.deployment.deploy()

        print(package_test.deployment.name)

