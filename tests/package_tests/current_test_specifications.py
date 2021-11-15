import abc
import base64
import collections
import dataclasses
import enum
import functools
import os.path
import pickle
import shlex
import shutil
import pathlib as pl
import subprocess
import sys
import stat
import tempfile
from typing import ClassVar, Dict, List, Union, Type


from agent_tools import constants
from agent_tools import environment_deployments as env_deployers
from agent_tools import package_builders
from tests.package_tests.internals import deb_rpm_tar_msi_test
from tests.package_tests.frozen_test_runner import build_test_runner_frozen_binary

_PARENT_DIR = pl.Path(__file__).parent
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.absolute()


class PackageTest:
    """
    Specification of the particular package test. If combines information about the package type, architecture,
    deployment and the system where test has to run.
    """

    ALL_TESTS: Dict[str, 'PackageTest'] = {}
    PACKAGE_TESTS: Dict[str, List['PackageTest']] = collections.defaultdict(list)

    def __init__(
            self,
            test_name: str,
            package_builder: package_builders.PackageBuilder,
            deployment_step_classes: List[Type[env_deployers.DeploymentStep]],
            architecture: constants.Architecture = None,
    ):
        self.test_name = test_name
        self.package_builder = package_builder
        self.architecture = architecture or package_builder.architecture

        if not deployment_step_classes:
            deployment_step_classes = package_builder.DEPLOYMENT_STEPS[:]

        self.deployment = env_deployers.Deployment(
            name=f"package_test_{self.unique_name}_deployment",
            step_classes=deployment_step_classes,
            architecture=architecture or package_builder.architecture,
            base_docker_image=package_builder.BASE_DOCKER_IMAGE
        )

        if self.unique_name not in type(self).ALL_TESTS:
            type(self).ALL_TESTS[self.unique_name] = self
            type(self).PACKAGE_TESTS[self.package_builder.name].append(self)

    # test_name: str
    # package_build_spec: package_builders.PackageBuildSpec
    # deployment_spec: env_deployers.DeploymentSpec

    @property
    def unique_name(self) -> str:
        """
        The unique name of the package test spec. It contains information about all specifics that the spec has.
        :return:
        """
        return f"{self.package_builder.name}_{self.test_name}".replace("-", "_")

    def run_test_locally(
            self,
            package_path: pl.Path,
            scalyr_api_key: str,
            locally: bool = False
    ):

        if self.package_builder.PACKAGE_TYPE in [
            constants.PackageType.DEB,
            constants.PackageType.RPM,
            constants.PackageType.TAR,
            constants.PackageType.MSI
        ]:
            deb_rpm_tar_msi_test.run(
                package_type=self.package_builder.PACKAGE_TYPE,
                package_path=package_path,
                scalyr_api_key=scalyr_api_key
            )
            return

    @staticmethod
    def create_test_specs(
            base_name: str,
            package_builders: List[package_builders.PackageBuilder],
            additional_deployment_steps: List[Type[env_deployers.DeploymentStep]],
            remote_machine_arch_specs: Dict[constants.Architecture, List[Union[
                'RemoteMachinePackageTest.Ec2MachineInfo']]] = None,

    ):
        """
        Creates multiple test specs based on given specifics and put them into the global class attribute list.
        :param base_name: Common name for all produced tests.
        :param package_build_specs: Specification for the package to build.
        :param deployment: Deployment which ir required to perform the test.
        :param remote_machine_arch_specs: Specification of the "remote" machines to run the test in them instead of the
            current system. This is a dict where each element is a list of specifications of the remote machines for a
            particular processor architecture.
        """

        additional_deployment_steps = additional_deployment_steps or []

        remote_machine_arch_specs = remote_machine_arch_specs or {}

        for builder in package_builders:

            package_tests = []

            remote_machine_specs = remote_machine_arch_specs.get(builder.architecture, [])

            for remote_machine_spec in remote_machine_specs:

                kwargs = {
                    "test_name": base_name,
                    "package_builder": builder,
                    "deployment_step_classes": [*builder.DEPLOYMENT_STEPS, *additional_deployment_steps]
                }
                if isinstance(remote_machine_spec, DockerBasedPackageTest.DockerImageInfo):
                    test_spec = DockerBasedPackageTest(
                        **kwargs,
                        docker_image_info=remote_machine_spec,
                    )
                elif isinstance(remote_machine_spec, Ec2BasedPackageTest.Ec2MachineInfo):
                    test_spec = Ec2BasedPackageTest(
                        **kwargs,
                        ec2_machine_info=remote_machine_spec
                    )
                else:
                    test_spec = PackageTest(
                        **kwargs,
                    )

                package_tests.append(test_spec)

            for package_test in list(package_tests):
                if package_test.unique_name in PackageTest.ALL_TESTS:
                    package_tests.remove(package_test)
                else:
                    PackageTest.ALL_TESTS[package_test.unique_name] = package_test

            PackageTest.ALL_TESTS[builder.name] = package_tests



# class LocalPackageTest(PackageTest):
#     """
#     Subclass of the package test spec which is only has to be run locally, on the current system (not in docker or ec2).
#     """
#     # def __init__(
#     #         self,
#     #         test_name: str,
#     #         package_builder: package_builders.PackageBuilder,
#     #         architecture: constants.Architecture = None,
#     #         deployment_steps: List[env_deployers.DeploymentStep] = None,
#     #
#     # ):
#     #     super(LocalPackageTest, self).__init__(
#     #         test_name=test_name,
#     #         package_builder=package_builder,
#     #         architecture=architecture,
#     #         deployment_steps=deployment_steps
#     #     )
#
#     def run_test_locally(
#             self,
#             package_path: pl.Path,
#             scalyr_api_key: str,
#     ):
#
#         if self.package_builder.PACKAGE_TYPE in [
#             constants.PackageType.DEB,
#             constants.PackageType.RPM,
#             constants.PackageType.TAR,
#             constants.PackageType.MSI
#         ]:
#             deb_rpm_tar_msi_test.run(
#                 package_type=self.package_builder.PACKAGE_TYPE,
#                 package_path=package_path,
#                 scalyr_api_key=scalyr_api_key
#             )
#             return


class RemoteMachinePackageTest(PackageTest):
    REMOTE_MACHINE_SUFFIX = str
    """
    Subclass of the package test spec which has to performed on the different machine, for example docker or ec2 instance.
    """

    # Reference the base local test spec. Since the current spec is "remote", it has to have a reference to its local
    # variant to run it on the remote machine.
    base_spec: PackageTest

    @property
    def unique_name(self) -> str:
        """
        Add the remote machine's type as suffix to the name to avoid name collisions with the local test specs.
        """
        name = super(RemoteMachinePackageTest, self).unique_name
        return f"{name}_{self.REMOTE_MACHINE_SUFFIX}"


class DockerBasedPackageTest(RemoteMachinePackageTest):
    """
    Specification of the package test that has to be performed in the docker.
    """
    REMOTE_MACHINE_SUFFIX = "docker"

    @dataclasses.dataclass
    class DockerImageInfo:
        """
        Docker image information class.
        """
        image_name: str

    def __init__(
            self,
            test_name: str,
            package_builder: package_builders.PackageBuilder,
            docker_image_info: DockerImageInfo,
            architecture: constants.Architecture = None,
            deployment_step_classes: List[Type[env_deployers.DeploymentStep]] = None,

    ):
        super(DockerBasedPackageTest, self).__init__(
            test_name=test_name,
            package_builder=package_builder,
            architecture=architecture,
            deployment_step_classes=deployment_step_classes,
        )

        self.docker_image_info = docker_image_info

    def run(
            self,
            package_path: pl.Path,
            scalyr_api_key: str,
            frozen_test_runner_path: pl.Path
    ):
        # Run the test inside the docker.
        # fmt: off

        cmd_args = []

        subprocess.check_call(
            [
                "docker", "run", "-i", "--rm", "--init",
                "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
                "-v", f"{package_path}:/tmp/{package_path.name}",
                "-v", f"{frozen_test_runner_path}:/tmp/test_executable",
                "--workdir",
                "/tmp",
                "--platform",
                self.package_builder.architecture.as_docker_platform.value,
                # specify the image.
                self.docker_image_info.image_name,
                # Command to run the test executable inside the container.
                "/tmp/test_executable",
                self.unique_name,
                "--package-path",
                f"/tmp/{package_path.name}",
                "--scalyr-api-key",
                scalyr_api_key

            ]
        )
        # fmt: on


class Ec2BasedPackageTest(RemoteMachinePackageTest):
    REMOTE_MACHINE_SUFFIX = "ec2"

    @dataclasses.dataclass
    class Ec2MachineInfo:
        """Specification for the AWS Ec2 machine."""

        class Ec2PlatformType(enum.Enum):
            """Type of the operating system which is needed for the ec2 based tests."""
            WINDOWS = 1
            LINUX = 2

        image_name: str
        image_id: str
        size_id: str
        ssh_username: str
        os_family: Ec2PlatformType

    def __init__(
            self,
            test_name: str,
            package_builder: package_builders.PackageBuilder,
            ec2_machine_info: Ec2MachineInfo,
            architecture: constants.Architecture = None,
            deployment_step_classes: List[Type[env_deployers.DeploymentStep]] = None,

    ):
        super(Ec2BasedPackageTest, self).__init__(
            test_name=test_name,
            package_builder=package_builder,
            architecture=architecture,
            deployment_step_classes=deployment_step_classes,
        )

        self.ec2_machine_info = ec2_machine_info


def run_package_test(
    package_test_name: str,
    scalyr_api_key: str,
    build_dir_path: pl.Path = None,
    package_path: pl.Path = None,
    aws_access_key: str = None,
    aws_secret_key: str = None,
    aws_keypair_name: str = None,
    aws_private_key_path: str = None,
    aws_security_groups: str = None,
    aws_region=None,

):
    """
    Run package test based on some specification. According to the test's specification type, it may be performed locally,
    in docker or ec2 machine.
    :param package_test: Package test specification.
    :param scalyr_api_key: API key to be able to send logs to Scalyr during tests.
    :param build_dir_path: Optional directory where all needed builds are performed. Temporary folder is created if
        not specified.
    :param package_path: Package to test. If not specified, then the package has to be built in place.
    :param aws_access_key: Access key to AWS, needed to perform test in ec2 machine.
    :param aws_secret_key: Secret key to AWS, needed to perform test in ec2 machine.
    :param aws_keypair_name: Name of the SSH keypair, needed to perform test in ec2 machine.
    :param aws_private_key_path: Path to SSH private key, needed to perform test in ec2 machine.
    :param aws_security_groups: AWS EC2 security group names, needed to perform test in ec2 machine.
    :param aws_region: AWS region, needed to perform test in ec2 machine.
    """

    package_test = PackageTest.ALL_TESTS[package_test_name]

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

    if not isinstance(package_test, RemoteMachinePackageTest):
        package_test.run_test_locally(
            package_path=package_path,
            scalyr_api_key=scalyr_api_key
        )
        return

    frozen_test_runner_build_dir_path = build_dir_path / "frozen_test_runner"
    if frozen_test_runner_build_dir_path.exists():
        shutil.rmtree(frozen_test_runner_build_dir_path)

    frozen_test_runner_build_dir_path.mkdir(parents=True)

    package_test.deployment.deploy()

    test_runner_filename = "frozen_test_runner"

    build_test_runner_frozen_binary.build_test_runner_frozen_binary(
        output_path=frozen_test_runner_build_dir_path,
        filename=test_runner_filename,
        architecture=package_test.architecture,
        base_image_name=package_test.deployment.result_image_name,
    )

    frozen_test_runner_path = frozen_test_runner_build_dir_path / test_runner_filename

    if isinstance(package_test, DockerBasedPackageTest):

        # Run the test inside the docker.
        # fmt: off
        subprocess.check_call(
            [
                "docker", "run", "-i", "--rm", "--init",
                "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
                "-v", f"{package_path}:/tmp/{package_path.name}",
                "-v", f"{frozen_test_runner_path}:/tmp/test_executable",
                "--workdir",
                "/tmp",
                "--platform",
                package_test.architecture.as_docker_platform.value,
                # specify the image.
                package_test.docker_image_info.image_name,
                # Command to run the test executable inside the container.
                "/tmp/test_executable",
                package_test.unique_name,
                "--package-path",
                f"/tmp/{package_path.name}",
                "--scalyr-api-key",
                scalyr_api_key

            ]
        )
        # fmt: on

        return

    if isinstance(package_test, Ec2BasedPackageTest):
        from tests.package_tests.internals import ec2_ami

        assert aws_access_key, "Need AWS access key."
        assert aws_secret_key, "Need AWS secret key."
        assert aws_keypair_name, "Need AWS keypair name."
        assert aws_private_key_path, "Need AWS keypair path."
        assert aws_security_groups, "Need AWS security groups."
        assert aws_region, "Need AWS region"

        ec2_ami.main(
            distro=package_test.ec2_machine_info,
            to_version=str(package_path),
            frozen_test_runner_path=frozen_test_runner_path,
            access_key=aws_access_key,
            secret_key=aws_secret_key,
            keypair_name=aws_keypair_name,
            private_key_path=aws_private_key_path,
            security_groups=aws_security_groups,
            region=aws_region,
            destroy_node=True
        )

##############################################################################################

# Define package test specification.

# By calling this helper function we create multiple test specs in one step.

# The each test spec gets its unique name, which consists from package type, test_name, architecture name and
# remote machine name, so by knowing the specifics of the desired test, it spec can be found by name.
# This feature used in the github actions CI/CD, where the package testing job only gets a unique name of the test spec
# as its input and runs the test by passing this unique name to the package test runner script.

# All created test specs are saved globally in the special collection which is defined as a class attribute
# of the spec class. Since we need only one collection, this approach should be fine for us.

# For example, the following function call has to produce 4 test specs for DEB package:
#   1. test DEP package with architecture x86_64 inside docker image 'ubuntu:14.04'
#   2. test DEP package with architecture arm64 inside docker image 'ubuntu:14.04' (the arm version will be used)
#   3. test DEP package with architecture x86_64 inside docker image 'ubuntu:14.04'
#   4. test DEP package with architecture arm64 inside docker image 'ubuntu:14.04' (the arm version will be used)
#

_EC2_PLATFORM_TYPE = Ec2BasedPackageTest.Ec2MachineInfo.Ec2PlatformType

LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT_STEPS = [

]

PackageTest.create_test_specs(
    base_name="ubuntu-1404",
    package_builders=[package_builders.DEB_X86_64_BUILDER],
    remote_machine_arch_specs={
        constants.Architecture.X86_64: [
            DockerBasedPackageTest.DockerImageInfo("ubuntu:14.04"),
            Ec2BasedPackageTest.Ec2MachineInfo(
                image_name="Ubuntu Server 14.04 LTS (HVM)",
                image_id="ami-07957d39ebba800d5",
                size_id="t2.small",
                ssh_username="ubuntu",
                os_family=_EC2_PLATFORM_TYPE.LINUX
            )
        ],
        constants.Architecture.ARM64: [
            DockerBasedPackageTest.DockerImageInfo("ubuntu:14.04")
        ]
    },
    additional_deployment_steps=[env_deployers.InstallTestRequirementsDeploymentStep]
)

COMMON_TEST_ENVIRONMENT = env_deployers.Deployment(
    name="test_environment_x86_64",
    architecture=constants.Architecture.X86_64,
    step_classes=[env_deployers.InstallBuildRequirementsStep],
)

# # Create specs for the DEB packages, which have to be performed in the ubuntu 16.04 distribution.
# PackageTest.create_test_specs(
#     base_name="ubuntu-1604",
#     package_build_specs=[package_builders.DEB_x86_64, package_builders.DEB_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("ubuntu:16.04")
#         ],
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
# # Create specs for the DEB packages, which have to be performed in the ubuntu 18.04 distribution.
# PackageTest.create_test_specs(
#     base_name="ubuntu-1804",
#     package_build_specs=[package_builders.DEB_x86_64, package_builders.DEB_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("ubuntu:18.04")
#         ],
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
# # Create specs for the DEB packages, which have to be performed in the ubuntu 20.04 distribution.
# PackageTest.create_test_specs(
#     base_name="ubuntu-2004",
#     package_build_specs=[package_builders.DEB_x86_64, package_builders.DEB_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("ubuntu:20.04")
#         ],
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
#
# # Create specs for the RPM packages, which have to be performed in the centos 7 distribution.
# PackageTest.create_test_specs(
#     base_name="centos-7",
#     package_build_specs=[package_builders.RPM_x86_64, package_builders.RPM_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("centos:7")
#         ],
#         constants.Architecture.ARM64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("centos:7")
#         ]
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
# # Create specs for the RPM packages, which have to be performed in the centos 8 distribution.
# PackageTest.create_test_specs(
#     base_name="centos-8",
#     package_build_specs=[package_builders.RPM_x86_64, package_builders.RPM_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("centos:8")
#         ],
#         constants.Architecture.ARM64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("centos:8")
#         ]
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
# # Create specs for the RPM packages, which have to be performed in the amazonlinux distribution.
# PackageTest.create_test_specs(
#     base_name="amazonlinux-2",
#     package_build_specs=[package_builders.RPM_x86_64, package_builders.RPM_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("amazonlinux:2")
#         ],
#         constants.Architecture.ARM64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("amazonlinux:2")
#         ]
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#
# # Create specs for the tar packages, which have to be performed in the ubuntu 20.04 distribution.
# # The tar package consists of the same frozen binary and it is already tested in the other package tests,
# # so it's just enough to perform basic sanity test for the tar package itself.
# PackageTest.create_test_specs(
#     base_name="ubuntu-2004",
#     package_build_specs=[package_builders.TAR_x86_64, package_builders.TAR_ARM64],
#     remote_machine_arch_specs={
#         constants.Architecture.X86_64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("ubuntu:20.04")
#         ],
#         constants.Architecture.ARM64: [
#             DockerBasedPackageTestSpec.DockerImageInfo("ubuntu:20.04")
#         ]
#     },
#     deployment=env_deployers.LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT
# )
#

# Create test specs which has to be performed in the windows distribution.
PackageTest.create_test_specs(
    base_name="windows",
    package_builders=[package_builders.MSI_x86_64_BUILDER],
    additional_deployment_steps=[env_deployers.InstallTestRequirementsDeploymentStep],
)

#
# env_deployers.DeploymentSpec.create_new_deployment_spec(
#     architecture=constants.Architecture.X86_64,
#     deployment=env_deployers.COMMON_TEST_ENVIRONMENT
# )
