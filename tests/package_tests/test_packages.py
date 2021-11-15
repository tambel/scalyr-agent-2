import argparse
import json
import pathlib as pl
import logging
import sys
import os

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from tests.package_tests import current_test_specifications

# class DockerImages(enum.Enum):
#     UBUNTU_1404 = "ubuntu:14.04"
#     UBUNTU_1604 = "ubuntu:16.04"
#
#
# def run_test_in_docker(
#     target_spec_name: str,
#     package_path: pl.Path,
#     frozen_test_runner_path: pl.Path,
#     docker_image: str,
#     architecture: constants.Architecture,
#     scalyr_api_key: str
# ):
#
#     # Run the test inside the docker.
#     # fmt: off
#     subprocess.check_call(
#         [
#             "docker", "run", "-i", "--rm", "--init",
#             "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
#             "-v", f"{package_path}:/tmp/package",
#             "-v", f"{frozen_test_runner_path}:/tmp/test_executable",
#             "--platform",
#             architecture.as_docker_platform.value,
#             # specify the image.
#             docker_image,
#             # Command to run the test executable inside the container.
#             "/tmp/test_executable",
#             "run",
#             target_spec_name,
#             "--package-path", f"/tmp/package",
#             "--locally",
#             "--scalyr-api-key", scalyr_api_key
#         ]
#     )
#     # fmt: on
#
#
# def run_test_in_ec2_instance(
#         test_spec_name: str,
#         package_path: pl.Path,
#         frozen_test_runner_path: pl.Path,
#         scalyr_api_key: str
# ):
#     from tests.package_tests import packages_sanity_tests
#
#     test_spec = SPECS[test_spec_name]
#
#
#     aws_access_key = get_option("aws_access_key")
#     aws_secret_key = get_option("aws_secret_key")
#     aws_keypair_name = get_option("aws_keypair_name")
#     aws_private_key_path = get_option("aws_private_key_path")
#     aws_security_groups = get_option("aws_security_groups")
#     aws_region = get_option("aws_region", "us-east-1")
#     scalyr_api_key = get_option("scalyr_api_key")
#
#     ami_image: packages_sanity_tests.Ec2MachineSpec = test_spec.remote_machine_spec
#
#     def create_command(test_runner_path_remote_path: str, package_remote_path: str):
#         command = [
#             test_runner_path_remote_path,
#             "run",
#             test_spec_name,
#             "--package-path",
#             package_remote_path,
#             "--scalyr-api-key",
#             scalyr_api_key,
#             "--locally"
#         ]
#         return shlex.join(command)
#
#     packages_sanity_tests.main(
#         distro=ami_image,
#         to_version=str(package_path),
#         create_remote_test_command=create_command,
#         test_runner_path=frozen_test_runner_path,
#         access_key=aws_access_key,
#         secret_key=aws_secret_key,
#         keypair_name=aws_keypair_name,
#         private_key_path=aws_private_key_path,
#         security_groups=aws_security_groups,
#         region=aws_region,
#         destroy_node=True
#     )
#
#
#
# def _prepare_build_dir(path: Union[str, pl.Path] = None):
#     if path:
#         return pl.Path(path)
#     else:
#         tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-package-test-")
#         return pl.Path(tmp_dir.name)
#
#
# def run_test_from_spec(
#         test_spec_name: str,
#         scalyr_api_key: str,
#         package_path: str,
#         build_dir_path: str = None,
#         locally: bool = False,
# ):
#     test_spec = tests.package_tests.package_test_specs.PackageTestSpec.ALL_TEST_SPECS[test_spec_name]
#
#     if not package_path:
#         if __frozen__:
#             raise ValueError("Package path has to be specified in frozen test runner.")
#
#         build_dir_path = _prepare_build_dir(build_dir_path)
#
#         package_output_dir_path = build_dir_path / "package"
#
#         if package_output_dir_path.exists():
#             shutil.rmtree(package_output_dir_path)
#         package_output_dir_path.mkdir(parents=True)
#
#         package_builders.PackageBuildSpec.build_package_from_spec_name(
#             package_build_spec_name=test_spec.package_build_spec.name,
#             output_path_dir=str(package_output_dir_path)
#         )
#         # test_spec.package_build_spec.build(
#         #     output_path=package_output_dir_path
#         # )
#
#         final_package_path = list(package_output_dir_path.glob(test_spec.package_build_spec.filename_glob))[0]
#     else:
#         final_package_path = pl.Path(package_path)
#
#     if locally or not test_spec.remote_machine_spec:
#         if test_spec.package_build_spec.package_type in [
#             constants.PackageType.DEB,
#             constants.PackageType.RPM,
#             constants.PackageType.TAR,
#             constants.PackageType.MSI
#         ]:
#             deb_rpm_tar_msi_test.run(
#                 package_path=final_package_path,
#                 package_build_spec=test_spec.package_build_spec,
#                 scalyr_api_key=scalyr_api_key
#             )
#             return
#
#     build_dir_path = _prepare_build_dir(build_dir_path)
#     frozen_test_runner_output_dir_path = build_dir_path / "frozen_test_runner"
#
#     if frozen_test_runner_output_dir_path.exists():
#         shutil.rmtree(frozen_test_runner_output_dir_path)
#     frozen_test_runner_output_dir_path.mkdir(parents=True)
#
#     test_spec.deployment_spec.deploy()
#
#     build_func = run_in_docker.dockerized_function(
#         func=build_test_runner_frozen_binary,
#         image_name=f"scalyr-agent-test-runner-builder-{test_spec.package_build_spec.name}",
#         base_image=test_spec.deployment_spec.result_image_name,
#         architecture=test_spec.deployment_spec.architecture,
#         build_stage="test",
#         path_mappings={frozen_test_runner_output_dir_path: "/tmp/build"}
#     )
#     build_func(
#         output_path_dir=str(frozen_test_runner_output_dir_path)
#     )
#
#     script_filename = pl.Path(__file__).stem
#     frozen_test_runner_path = list(frozen_test_runner_output_dir_path.glob(f"{script_filename}*"))[0]
#
#     if isinstance(test_spec.remote_machine_spec, tests.package_tests.package_test_specs.PackageTestSpec.DockerImageInfo):
#         run_test_in_docker(
#             target_spec_name=test_spec_name,
#             package_path=final_package_path,
#             frozen_test_runner_path=frozen_test_runner_path,
#             docker_image=test_spec.remote_machine_spec.image_name,
#             architecture=test_spec.deployment_spec.architecture,
#             scalyr_api_key=scalyr_api_key
#         )
#         return
#
#     if isinstance(test_spec.remote_machine_spec, packages_sanity_tests.Ec2MachineSpec):
#         run_test_in_ec2_instance(
#             test_spec_name=test_spec_name,
#             package_path=final_package_path,
#             frozen_test_runner_path=frozen_test_runner_path,
#             scalyr_api_key=scalyr_api_key
#         )

config_path = pl.Path(__file__).parent / "credentials.json"

if config_path.exists():
    config = json.loads(config_path.read_text())
else:
    config = {}


def get_option(name: str, default: str = None, type_=str, ):
    global config

    name = name.lower()

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




# def parse_args():
#     logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")
#
#     parser = argparse.ArgumentParser()
#
#     subparsers = parser.add_subparsers(dest="command", required=True)
#
#     test_specs = current_test_specifications.PackageTestSpec.ALL_TEST_SPECS
#
#     run_test_parser = subparsers.add_parser("run")
#     run_test_parser.add_argument("spec_name", choices=test_specs.keys())
#     run_test_parser.add_argument("--locally", required=False, action="store_true")
#     run_test_parser.add_argument("--build-dir-path", dest="build_dir_path")
#
#     args = parser.parse_args()
#
#     if args.command == "list":
#         for spec in current_test_specifications.PackageTestSpec.ALL_TEST_SPECS.keys():
#             print(spec)
#
#     if args.command == "run":
#         test_spec = test_specs[args.spec_name]
#         print(args)
#
#         aws_access_key = get_option("aws_access_key")
#         aws_secret_key = get_option("aws_secret_key")
#         aws_keypair_name = get_option("aws_keypair_name")
#         aws_private_key_path = get_option("aws_private_key_path")
#         aws_security_groups = get_option("aws_security_groups")
#         aws_region = get_option("aws_region", "us-east-1")
#
#         current_test_specifications.run_package_test_spec(
#             package_test_spec=test_spec,
#             scalyr_api_key=get_option("scalyr_api_key"),
#             build_dir_path=pl.Path(args.build_dir_path) if args.build_dir_path else None,
#             aws_access_key=aws_access_key,
#             aws_secret_key=aws_secret_key,
#             aws_keypair_name=aws_keypair_name,
#             aws_private_key_path=aws_private_key_path,
#             aws_security_groups=aws_security_groups,
#             aws_region=aws_region
#         )
#         sys.exit(0)


def pytest_generate_tests(metafunc):
    """
    Read names of the test specs from the pytest's command line and run tem.
    """
    spec_names = metafunc.config.getoption("--spec")

    metafunc.parametrize(
        "package_test_spec_name", spec_names
    )


def test_package(package_test_spec_name: str):
    test_spec = current_test_specifications.PackageTestSpec.ALL_TEST_SPECS[package_test_spec_name]
    current_test_specifications.run_package_test_spec(
        package_test_spec=test_spec,
        aws_access_key=get_option("aws_access_key"),
        aws_secret_key = get_option("aws_secret_key"),
        aws_keypair_name = get_option("aws_keypair_name"),
        aws_private_key_path = get_option("aws_private_key_path"),
        aws_security_groups = get_option("aws_security_groups"),
        aws_region=get_option("aws_region", "us-east-1"),
        scalyr_api_key=get_option("scalyr_api_key"),
    )
    print(package_test_spec_name)