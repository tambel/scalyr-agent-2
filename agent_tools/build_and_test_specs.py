import sys
import pathlib as pl
import dataclasses
import enum
import collections
import logging
import argparse
import json
import shutil
from typing import Dict, Type, List, Callable, Union, Optional


__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import environment_deployers as env_deployers
from agent_tools import constants
from agent_tools import package_builders
from agent_tools import run_in_docker


_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"
_SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployer_scripts"


base_environment_used_files = [
    __SOURCE_ROOT__ / _SCRIPTS_DIR_PATH / "cache_lib.sh",
    _AGENT_BUILD_DIR / "requirement-files" / "*.txt"
]

PYTHON_ENVIRONMENT_DEPLOYER = env_deployers.EnvironmentDeployer(
    name="python",
    deployment_script_path=_SCRIPTS_DIR_PATH / "install_python_and_ruby.sh"
)

BASE_ENVIRONMENT_DEPLOYER = env_deployers.EnvironmentDeployer(
    name="base_environment",
    deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_base_environment.sh",
    used_files=base_environment_used_files,
)


WINDOWS_INSTALL_WIX = env_deployers.EnvironmentDeployer(
    name="windows_agent_builder",
    deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1",
    used_files=base_environment_used_files,
)

TEST_ENVIRONMENT = env_deployers.EnvironmentDeployer(
    name="test_environment",
    deployment_script_path=_SCRIPTS_DIR_PATH / "deploy-dev-environment.sh",
    used_files=base_environment_used_files + [__SOURCE_ROOT__ / "dev-requirements.txt"],
)


# Map deployers to their names.
DEPLOYERS: Dict[str, env_deployers.EnvironmentDeployer] = {
    dep.name: dep for dep in [
        PYTHON_ENVIRONMENT_DEPLOYER,
        BASE_ENVIRONMENT_DEPLOYER,
        WINDOWS_INSTALL_WIX,
        TEST_ENVIRONMENT
    ]
}

_LINUX_SPECS_BASE_IMAGE = "centos:7"
_LINUX_BUILDER_DEPLOYERS = [
    PYTHON_ENVIRONMENT_DEPLOYER,
    BASE_ENVIRONMENT_DEPLOYER
]

_WINDOWS_BUILDER_DEPLOYERS = [
    WINDOWS_INSTALL_WIX,
    BASE_ENVIRONMENT_DEPLOYER
]

_DEFAULT_ARCHITECTURES = [
    constants.Architecture.X86_64, constants.Architecture.ARM64
]


def create_build_spec_name(
        package_type: constants.PackageType,
        architecture: constants.Architecture = None
):
    result = f"{package_type.value}"
    if architecture:
        result = f"{result}_{architecture.value}"

    return result


@dataclasses.dataclass
class DockerImageInfo:
    image_name: str


@dataclasses.dataclass
class PackageBuildSpec:
    package_type: constants.PackageType
    package_builder_cls: Type[package_builders.PackageBuilder]
    deployment: 'Deployment'
    filename_glob: str


    @property
    def architecture(self) -> constants.Architecture:
        return self.deployment.architecture

    @property
    def name(self) -> str:
        return create_build_spec_name(
            package_type=self.package_type,
            architecture=self.architecture
        )

    # @property
    # def used_deployers_string_array(self):
    #     used_deployer_names = [d.name for d in self.used_deployers]
    #     return ",".join(used_deployer_names)

    # @property
    # def used_deployers_info_as_dict(self):
    #     result = {
    #         "deployers": self.used_deployers_string_array,
    #         "architecture": package_build_spec.architecture.value
    #     }
    #
    #     if package_build_spec.base_image:
    #         result["base-docker-image"] = package_build_spec.base_image.image_name
    #
    #     return result

    def get_dockerized_function(
            self,
            func: Callable,
            build_stage: str,
            path_mappings: Dict[Union[str, pl.Path], Union[str, pl.Path]] = None
    ):

        if self.deployment.in_docker:
            self.deployment.deploy()

        base_image = self.deployment.image_name
        image_name = f"agent-builder-{self.name}-{base_image}".lower()

        wrapped_func = run_in_docker.dockerized_function(
            func=func,
            image_name=image_name,
            base_image=self.deployment.image_name,
            architecture=self.architecture,
            build_stage=build_stage,
            path_mappings=path_mappings

        )

        return wrapped_func

    def build(self, output_path: pl.Path):

        if self.deployment.in_docker:
            build_func = self.get_dockerized_function(
                func=self.build_package_from_spec,
                build_stage="build",
                path_mappings={output_path: "/tmp/build"}
            )
        else:
            build_func = self.build_package_from_spec

        print(build_func)
        build_func(
            package_build_spec_name=self.name,
            output_path_dir=str(output_path)
        )

    @staticmethod
    def build_package_from_spec(
            package_build_spec_name: str,
            output_path_dir: str,
            locally: bool = False,
            variant: str = None,
            no_versioned_file_name: bool = False
    ):
        output_path = pl.Path(output_path_dir)
        package_build_spec = PACKAGE_BUILD_SPECS[package_build_spec_name]
        if output_path.exists():
            shutil.rmtree(output_path)
        output_path.mkdir(parents=True)

        package_builder_cls = package_build_spec.package_builder_cls
        package_builder = package_builder_cls(
            architecture=package_build_spec.architecture,
            variant=variant, no_versioned_file_name=no_versioned_file_name
        )
        package_builder.build(
            output_path=output_path,
        )


def get_package_build_spec(
        package_build_spec: PackageBuildSpec
):
    used_deployer_names = [d.name for d in package_build_spec.used_deployers]
    used_deployers_str = ",".join(used_deployer_names)
    return {
        "deployers": used_deployers_str,
        "base-docker-image": package_build_spec.base_image,
        "architecture": package_build_spec.architecture.value
    }


PACKAGE_BUILD_SPECS: Dict[str, PackageBuildSpec] = {}

DEPLOYMENTS = {}


@dataclasses.dataclass
class Deployment:
    deployer: env_deployers.EnvironmentDeployer

    @property
    def architecture(self) -> constants.Architecture:
        pass

    @property
    def name(self) -> str:
        pass

    @property
    def initial_docker_image(self) -> Optional[str]:
        pass

    @property
    def base_docker_image(self) -> Optional[str]:
        pass

    @property
    def in_docker(self) -> bool:
        return self.initial_docker_image is not None

    @property
    def image_name(self):
        return f"{self.name}_{self.checksum}"


    @property
    def checksum(self) -> str:
        return self.deployer.get_used_files_checksum()

    def deploy(
            self,
            cache_dir: pl.Path=None,
            only_this: bool = False
    ):

        if cache_dir:
            deployment_cache_dir = pl.Path(cache_dir) / f"{self.name}_{self.checksum}"
        else:
            deployment_cache_dir = None

        if self.in_docker:
            logging.info(f"Perform the deployment '{self.name}' inside the docker.")
            self.deployer.run_in_docker(
                base_docker_image=self.base_docker_image,
                result_image_name=self.image_name,
                architecture=self.architecture,
                cache_dir=deployment_cache_dir
            )
        else:
            logging.info(f"Perform the deployment '{self.name}'.")
            self.deployer.run(
                cache_dir=deployment_cache_dir
            )



@dataclasses.dataclass
class InitialDeployment(Deployment):
    architecture_: constants.Architecture
    initial_docker_image_: str = None

    @property
    def architecture(self) -> constants.Architecture:
        return self.architecture_

    @property
    def initial_docker_image(self) -> Optional[str]:
        return self.initial_docker_image_

    @property
    def base_docker_image(self) -> Optional[str]:
        return self.initial_docker_image_

    @property
    def name(self):
        name = f"{self.deployer.name}_{self.architecture.value}"
        if self.in_docker:
            docker_image_name = self.initial_docker_image.replace(":", "_")
            name = f"{name}_{docker_image_name}"
        return name


@dataclasses.dataclass
class FollowingDeployment(Deployment):
    previous_deployment: Deployment

    @property
    def architecture(self) -> constants.Architecture:
        return self.previous_deployment.architecture

    @property
    def name(self) -> str:
        return f"{self.deployer.name}_{self.previous_deployment.name}"

    @property
    def initial_docker_image(self):
        return self.previous_deployment.initial_docker_image

    @property
    def base_docker_image(self) -> Optional[str]:
        return self.previous_deployment.image_name

    @property
    def checksum(self) -> str:
        return self.deployer.get_used_files_checksum(
            additional_seed=self.previous_deployment.image_name
        )


    def deploy(
            self,
            cache_dir: pl.Path = None,
            only_this: bool = False
    ):

        if not only_this:
            self.previous_deployment.deploy(
                cache_dir=cache_dir
            )

        super(FollowingDeployment, self).deploy(
            cache_dir=cache_dir
        )


def _create_new_deployment(
    architecture: constants.Architecture,
    deployers: List[env_deployers.EnvironmentDeployer],
    base_docker_image: str = None
) -> Deployment:

    global DEPLOYMENTS

    all_deployers = deployers[:]

    initial_deployment = InitialDeployment(
        deployer=all_deployers.pop(0),
        architecture_=architecture,
        initial_docker_image_=base_docker_image
    )

    existing_deployment = DEPLOYMENTS.get(initial_deployment.name)

    if existing_deployment:
        initial_deployment = existing_deployment
    else:
        DEPLOYMENTS[initial_deployment.name] = initial_deployment

    previous_deployment = initial_deployment

    all_deployments = [initial_deployment]

    for deployer in all_deployers:
        deployment = FollowingDeployment(
            deployer=deployer,
            previous_deployment=previous_deployment
        )

        existing_deployment = DEPLOYMENTS.get(deployment.name)
        if existing_deployment:
            deployment = existing_deployment
        else:
            DEPLOYMENTS[deployment.name] = deployment

        previous_deployment = deployment
        all_deployments.append(deployment)
        DEPLOYMENTS[deployment.name] = deployment

    return all_deployments[-1]


def _add_package_build_specs(
        package_type: constants.PackageType,
        package_builder_cls: Type[package_builders.PackageBuilder],
        filename_glob_format: str,
        architectures: List[constants.Architecture],
        used_deployers: List[env_deployers.EnvironmentDeployer] = None,
        base_docker_image: str = None,

):
    global PACKAGE_BUILD_SPECS, DEPLOYMENTS

    specs = []

    for arch in architectures:

        # if base_docker_image:
        #     base_docker_image_spec = DockerImageInfo(
        #         image_name=base_docker_image,
        #     )
        # else:
        #     base_docker_image_spec = None

        deployment = _create_new_deployment(
            architecture=arch,
            deployers=used_deployers,
            base_docker_image=base_docker_image
        )

        package_arch_name = package_builder_cls.PACKAGE_FILENAME_ARCHITECTURE_NAMES.get(arch, "")

        spec = PackageBuildSpec(
            package_type=package_type,
            package_builder_cls=package_builder_cls,
            filename_glob=filename_glob_format.format(arch=package_arch_name),
            deployment=deployment,
            # architecture=arch,
            # base_image=base_docker_image_spec
        )
        # spec_name = create_build_spec_name(
        #     package_type=package_type,
        #     architecture=arch
        # )
        PACKAGE_BUILD_SPECS[spec.name] = spec
        specs.append(spec)

    return specs


DEB_x86_64, DEB_ARM64 = _add_package_build_specs(
    package_type=constants.PackageType.DEB,
    package_builder_cls=package_builders.DebPackageBuilder,
    filename_glob_format="scalyr-agent-2_*.*.*_{arch}.deb",
    used_deployers=_LINUX_BUILDER_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
RPM_x86_64, RPM_ARM64 = _add_package_build_specs(
    package_type=constants.PackageType.RPM,
    package_builder_cls=package_builders.RpmPackageBuilder,
    filename_glob_format="scalyr-agent-2-*.*.*-*.{arch}.rpm",
    used_deployers=_LINUX_BUILDER_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
TAR_x86_64, TAR_ARM64 = _add_package_build_specs(
    package_type=constants.PackageType.TAR,
    package_builder_cls=package_builders.TarballPackageBuilder,
    filename_glob_format="scalyr-agent-*.*.*_{arch}.tar.gz",
    used_deployers=_LINUX_BUILDER_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
MSI_x86_64, = _add_package_build_specs(
    package_type=constants.PackageType.MSI,
    package_builder_cls=package_builders.MsiWindowsPackageBuilder,
    filename_glob_format="ScalyrAgentInstaller-*.*.*.msi",
    used_deployers=_WINDOWS_BUILDER_DEPLOYERS,
    architectures=[constants.Architecture.X86_64]
)


class TargetSystem(enum.Enum):
    UBUNTU_1404 = "ubuntu-1404"
    UBUNTU_2004 = "ubuntu-2004"

    AMAZONLINUX_2 = "amazonlinux-2"

    WINDOWS_2019 = "windows-2019"


class OSFamily(enum.Enum):
    WINDOWS = 1
    LINUX = 2


@dataclasses.dataclass
class Ec2BasedTestSpec:
    image_name: str
    image_id: str
    size_id: str
    ssh_username: str
    os_family: OSFamily


@dataclasses.dataclass
class PackageTestSpec:
    target_system: TargetSystem
    package_build_spec: PackageBuildSpec
    deployment: Deployment
    remote_machine_spec: Union[DockerImageInfo, Ec2BasedTestSpec] = None


    @property
    def name(self):
        return f"{self.package_build_spec.package_type.value}_{self.target_system.value}_{self.package_build_spec.architecture.value}"


TEST_SPECS: Dict[str, PackageTestSpec] = {}
PACKAGE_BUILD_TO_TEST_SPECS: Dict[str, List[PackageTestSpec]] = collections.defaultdict(list)


def create_test_spec(
        target_system: TargetSystem,
        package_build_spec: PackageBuildSpec,
        remote_machine_specs: List[Union[DockerImageInfo, Ec2BasedTestSpec]] = None,
        additional_deployers: List[env_deployers.EnvironmentDeployer] = None
):

    global TEST_SPECS, PACKAGE_BUILD_TO_TEST_SPECS

    package_build_spec_name = create_build_spec_name(
        package_type=package_build_spec.package_type,
        architecture=package_build_spec.architecture
    )
    test_spec_name = f"{package_build_spec.package_type.value}_{target_system.value}_{package_build_spec.architecture.value}"
    if remote_machine_specs:
        for remote_machine_spec in remote_machine_specs:
            if isinstance(remote_machine_spec, DockerImageInfo):
                remote_machine_suffix = "docker"
            elif isinstance(remote_machine_spec, Ec2BasedTestSpec):
                remote_machine_suffix = "ec2"
            else:
                raise ValueError(f"Wrong remote machine spec: {remote_machine_spec}")

            full_name = f"{test_spec_name}_{remote_machine_suffix}"

            spec = PackageTestSpec(
                name=full_name,
                target_system=target_system,
                package_build_spec=package_build_spec,
                remote_machine_spec=remote_machine_spec,
                additional_deployers=additional_deployers
            )
            TEST_SPECS[full_name] = spec
            PACKAGE_BUILD_TO_TEST_SPECS[package_build_spec_name].append(spec)
    else:
        spec = PackageTestSpec(
            name=test_spec_name,
            target_system=target_system,
            package_build_spec=package_build_spec,
            additional_deployers=additional_deployers
        )

        TEST_SPECS[test_spec_name] = spec
        PACKAGE_BUILD_TO_TEST_SPECS[package_build_spec_name].append(spec)

def create_test_specs(
        target_system: TargetSystem,
        package_build_specs: List[PackageBuildSpec],
        remote_machine_arch_specs: Dict[constants.Architecture, List[Union[DockerImageInfo, Ec2BasedTestSpec]]] = None,
        additional_deployers: List[env_deployers.EnvironmentDeployer] = None
):

    global TEST_SPECS, PACKAGE_BUILD_TO_TEST_SPECS

    remote_machine_arch_specs = remote_machine_arch_specs or {}

    for build_spec in package_build_specs:

        deployment = _create_new_deployment(
            architecture=build_spec.architecture,
            deployers=additional_deployers,
            base_docker_image=build_spec.deployment.initial_docker_image
        )

        test_spec_name = f"{build_spec.package_type.value}_{target_system.value}_{build_spec.architecture.value}"

        remote_machine_specs = remote_machine_arch_specs.get(build_spec.architecture)
        if remote_machine_specs:
            for remote_machine_spec in remote_machine_specs:
                if isinstance(remote_machine_spec, DockerImageInfo):
                    remote_machine_suffix = "docker"
                elif isinstance(remote_machine_spec, Ec2BasedTestSpec):
                    remote_machine_suffix = "ec2"
                else:
                    raise ValueError(f"Wrong remote machine spec: {remote_machine_spec}")

                full_name = f"{test_spec_name}_{remote_machine_suffix}"

                spec = PackageTestSpec(
                    target_system=target_system,
                    package_build_spec=build_spec,
                    remote_machine_spec=remote_machine_spec,
                    deployment=deployment
                )
                TEST_SPECS[full_name] = spec
                PACKAGE_BUILD_TO_TEST_SPECS[build_spec.name].append(spec)
        else:
            spec = PackageTestSpec(
                target_system=target_system,
                package_build_spec=build_spec,
                deployment=deployment
            )

            TEST_SPECS[test_spec_name] = spec
            PACKAGE_BUILD_TO_TEST_SPECS[build_spec.name].append(spec)


create_test_specs(
    target_system=TargetSystem.UBUNTU_1404,
    package_build_specs=[DEB_x86_64, DEB_ARM64],
    remote_machine_arch_specs={
        constants.Architecture.X86_64: [
            DockerImageInfo("ubuntu:14.04")
        ],
        constants.Architecture.ARM64: [
            DockerImageInfo("ubuntu:14.04")
        ]
    },
    additional_deployers=_LINUX_BUILDER_DEPLOYERS + [TEST_ENVIRONMENT]
)

create_test_specs(
    target_system=TargetSystem.AMAZONLINUX_2,
    package_build_specs=[RPM_x86_64, RPM_ARM64],
    remote_machine_arch_specs={
        constants.Architecture.X86_64: [
            DockerImageInfo("amazonlinux:2")
        ],
        constants.Architecture.ARM64: [
            DockerImageInfo("amazonlinux:2")
        ]
    },
    additional_deployers=_LINUX_BUILDER_DEPLOYERS + [TEST_ENVIRONMENT]
)

create_test_specs(
    target_system=TargetSystem.UBUNTU_2004,
    package_build_specs=[TAR_x86_64, TAR_ARM64],
    remote_machine_arch_specs={
        constants.Architecture.X86_64: [
            DockerImageInfo("ubuntu:20.04")
        ],
    },
    additional_deployers=_LINUX_BUILDER_DEPLOYERS + [TEST_ENVIRONMENT]
)

create_test_specs(
    target_system=TargetSystem.WINDOWS_2019,
    package_build_specs=[MSI_x86_64],
    additional_deployers=_WINDOWS_BUILDER_DEPLOYERS + [TEST_ENVIRONMENT]
)


# create_test_spec(
#     target_system=TargetSystem.UBUNTU_1404,
#     package_build_spec=DEB_x86_64,
#     remote_machine_specs=[
#         DockerImageInfo("ubuntu:14.04"),
#         # Ec2BasedTestSpec(
#         #     image_name="Ubuntu Server 14.04 LTS (HVM)",
#         #     image_id="ami-07957d39ebba800d5",
#         #     size_id="t2.small",
#         #     ssh_username="ubuntu",
#         #     os_family=OSFamily.LINUX
#         # )
#     ],
#     additional_deployers=[TEST_ENVIRONMENT]
# )
# create_test_spec(
#     target_system=TargetSystem.UBUNTU_1404,
#     package_build_spec=DEB_ARM64,
#     remote_machine_specs=[
#         DockerImageInfo("ubuntu:14.04"),
#     ],
#     additional_deployers=[TEST_ENVIRONMENT]
# )
#
# create_test_spec(
#     target_system=TargetSystem.AMAZONLINUX_2,
#     package_build_spec=RPM_x86_64,
#     remote_machine_specs=[
#         DockerImageInfo("amazonlinux:2"),
#     ],
# )
#
# create_test_spec(
#     target_system=TargetSystem.UBUNTU_2004,
#     package_build_spec=TAR_x86_64,
#     remote_machine_specs=[
#         DockerImageInfo("ubuntu:20.04"),
#     ],
# )
#
# create_test_spec(
#     target_system=TargetSystem.WINDOWS_2019,
#     package_build_spec=MSI_x86_64,
#     additional_deployers=[TEST_ENVIRONMENT]
# )


def get_deployer_names_as_string_array(
        deployers: List[env_deployers.EnvironmentDeployer],
):
    deployer_names = [d.name for d in deployers]
    return ",".join(deployer_names)


def deployers_info_as_dict(
        deployers: List[env_deployers.EnvironmentDeployer],
        architecture: constants.Architecture,
        base_docker_image: Optional[DockerImageInfo] = None
):
    result = {
        "deployers": get_deployer_names_as_string_array(deployers),
        "architecture": architecture.value
    }

    if base_docker_image:
        result["base-docker-image"] = base_docker_image.image_name

    return result

# if __name__ == '__main__':
#
#     logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")
#
#     parser = argparse.ArgumentParser()
#
#     subparsers = parser.add_subparsers(dest="command")
#
#     # build_frozen_test_runner = subparsers.add_parser("build-frozen-test-runner")
#     # build_frozen_test_runner.add_argument("spec_name", choices=SPECS.keys())
#     # build_frozen_test_runner.add_argument("--output-dir", dest="output_dir")
#     # build_frozen_test_runner.add_argument("--locally", required=False, action="store_true")
#
#     test_specs_info_parser = subparsers.add_parser("get-package-test-specs")
#     test_specs_info_parser.add_argument("package_type", choices=PACKAGE_BUILD_SPECS.keys())
#
#     package_deployers_parser = subparsers.add_parser("get-package-build-spec-info")
#     package_deployers_parser.add_argument("package_type", choices=PACKAGE_BUILD_SPECS.keys())
#
#     deployer_parser = subparsers.add_parser("deployer")
#     deployer_parser.add_argument("deployer_name", choices=DEPLOYERS.keys())
#     deployer_parser.add_argument("deployer_command", choices=["deploy", "checksum", "result-image-name"])
#     deployer_parser.add_argument("--base-docker-image", dest="base_docker_image")
#     deployer_parser.add_argument("--cache-dir", dest="cache_dir")
#     deployer_parser.add_argument("--architecture")
#
#     # deployer_subparsers = deployer_parser.add_subparsers(dest="deployer_command")
#     #
#     # deploy_parser = deployer_subparsers.add_parser("deploy")
#
#
#     # deployer_parser.add_argument("name", choices=DEPLOYERS.keys())
#     # deployer_parser.add_argument("action", choices=["deploy", "checksum"])
#     # deployer_parser.add_argument("--cache-dir", dest="cache_dir")
#     # deployer_parser.add_argument("--base-docker-image", dest="base_docker_image")
#     # deployer_parser.add_argument("--architecture")
#
#     args = parser.parse_args()
#
#     if args.command == "get-package-build-spec-info":
#         package_build_spec = PACKAGE_BUILD_SPECS[args.package_type]
#         #package_build_spec_dict = package_build_spec.used_deployers_info_as_dict
#         package_build_spec_dict = deployers_info_as_dict(
#             deployers=package_build_spec.used_deployers,
#             architecture=package_build_spec.architecture,
#             base_docker_image=package_build_spec.base_image
#         )
#         package_build_spec_dict["package-filename-glob"] = package_build_spec.filename_glob
#         matrix = {"include": [package_build_spec_dict]}
#         print(
#             json.dumps(matrix)
#         )
#         exit(0)
#
#     if args.command == "get-package-test-specs":
#
#         package_build_spec = PACKAGE_BUILD_SPECS[args.package_type]
#         test_specs = PACKAGE_BUILD_TO_TEST_SPECS[args.package_type]
#
#         result_spec_infos = []
#
#         for test_spec in test_specs:
#             spec_info = {}
#
#             all_deployers = package_build_spec.used_deployers[:]
#             if test_spec.additional_deployers:
#                 all_deployers.extend(test_spec.additional_deployers)
#
#             spec_info = deployers_info_as_dict(
#                 deployers=all_deployers,
#                 architecture=package_build_spec.architecture,
#                 base_docker_image=package_build_spec.base_image
#             )
#
#             spec_info["spec_name"] = test_spec.name
#
#             result_spec_infos.append(spec_info)
#
#         print(json.dumps({"include": result_spec_infos}))
#
#         sys.exit(0)
#
#     if args.command == "deployer":
#         deployer = DEPLOYERS[args.deployer_name]
#         if args.deployer_command == "deploy":
#             if args.base_docker_image:
#                 deployer.run_in_docker(
#                     base_docker_image=args.base_docker_image,
#                     architecture=constants.Architecture(args.architecture),
#                     cache_dir=args.cache_dir,
#                 )
#             else:
#                 deployer.run(
#                     cache_dir=args.cache_dir
#                 )
#
#             exit(0)
#
#         if args.deployer_command == "checksum":
#             checksum = deployer.get_used_files_checksum()
#             print(checksum)
#             exit(0)
#
#         if args.deployer_command == "result-image-name":
#             image_name = deployer.get_image_name(constants.Architecture(args.architecture))
#             print(image_name)

