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

# This is a helper library/script which can be used to deploy needed tools and programs.
# It contains a set of pre-defined "deployers" which are, basically, wrappers of a shell scripts, and
# when those deployers are executed, they run their shell scripts. The whole purpose of deployers is to
# provide unified and also "CI/CD platform agnostic" way of creating environments where agent packages are built.

# Usage as script:
#   Run some deployer directly on the current system:
#       python3 deployers.py <deployer_name> deploy
#
#
#   Run deployer with using caching:
#       python3 deployers.py <deployer_name> deploy --cache-dir <cache_dir_path>
#
#       The cache directory is passed to the shell script, so the shell script can save some intermediate results to
#           it, or, in opposite, reuse them. This, as a result, should help to decrease overall time of the deployment.
#
#
#   Run some deployer inside of the docker:
#       python3 deployers.py <deployer_name> deploy --base-docker-image <image_name>
#
#       Specify base docker image, and the deployer will be executed inside it. The result of the deployment will
#           be in the new image. If the --cache-dir option is also specified, then the new image will be saved in the
#           cache directory as tar file (by using docker save).
#
#
#   Get checksum of the deployer:
#       python3 deployers.py <deployer_name> get-info checksum
#
#       This dumps the checksum to the standard output. The checksum is calculated using all files (including shell
#           script) that are used during the deployment, so it can be used as a cache key to store cached files which
#           are produced by using --cache-dir option. Mainly, the checksum has to be helpful when it is used in CI/CD
#           platforms to utilize their caching mechanisms.
#
#
import dataclasses
import pathlib as pl
import shutil
import subprocess
import hashlib
import logging
import re

from typing import Union, Optional, List, Dict, ClassVar, Type

__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent

_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"

from agent_tools import constants


class DeploymentStep:
    """
    This abstraction responsible for running of the some set of instructions in the target machine.
    Basically, it is just a wrapper around some shell script and a set of files which are used by this shell.

    Knowing what files are used, the step can calculate their checksum, and this can be uses as a cache key for
        some CI/CD platform, providing "CI/CD platform agnostic" and unified way of preparing/deploying needed
        environments.

    The deployment step can also run its script inside docker.

    Deployment steps are used in this project to prepare build and test environments for the agent. Using their ability to
        operate inside the docker, they help to achieve a unified way of building and testing agent packages, locally
        and on CI/CD.
    """

    SCRIPT_PATH: pl.Path
    USED_FILES: List[pl.Path] = []

    ALL_DEPLOYMENT_STEPS: Dict[str, 'DeploymentStep'] = {}

    def __init__(
            self,
            #name: str,
            #deployment_script_path: Union[str, pl.Path],
            #used_files: list = None,
            architecture: constants.Architecture,
            base_docker_image: str = None,
            previous_step: 'DeploymentStep' = None
    ):
        """
        :param name: Name of the deployment step.
        :param deployment_script_path: Path to the script which is executed during the step.
        :param used_files: List files used in the deployment step. Can be globs.
        """
        # self._name = name
        # self._script_path = deployment_script_path
        # self._used_files = used_files or []

        self.architecture = architecture
        self.base_docker_image = base_docker_image
        self.previous_step = previous_step

        if not base_docker_image:
            if previous_step:
                self.base_docker_image = previous_step.result_image_name
        else:
            self.base_docker_image = base_docker_image

        type(self).ALL_DEPLOYMENT_STEPS[self.name] = self

    @property
    def initial_docker_image(self) -> str:
        if not self.previous_step:
            return self.base_docker_image

        return self.previous_step.initial_docker_image

    # @property
    # def base_docker_image(self) -> str:
    #     if self._base_docker_image:
    #         return self._base_docker_image
    #
    #     if self.previous_step:
    #         return self.previous_step.base_docker_image

    @property
    def in_docker(self) -> bool:
        return self.initial_docker_image is not None

    @property
    def checksum(self) -> str:
        additional_checksum_seed = None
        if self.previous_step:
            additional_checksum_seed = self.previous_step.checksum

        return self.get_used_files_checksum(
            additional_seed=additional_checksum_seed
        )


    @property
    def name(self) -> str:
        """
        Name of the deployment step. It is just a name of the class name but in snake case.
        """
        class_name = type(self).__name__
        return re.sub(r'(?<!^)(?=[A-Z])', '_', class_name).lower()

    @property
    def unique_name(self) -> str:
        """
        Create name for the step. It has to contain all specific information about the step,
        so it can be used as unique cache key.
        """

        name = self.name

        if self.previous_step:
            name = f"{name}_{self.previous_step.name}"

        name = f"{name}_{self.architecture.value}"

        # If its a docker deployment, then add the docker image to the name
        if self.in_docker:
            image_suffix = self.initial_docker_image.replace(":", "_")
            name = f"{name}_{image_suffix}"

        return name

    @property
    def cache_name(self) -> str:
        return f"{self.unique_name}_{self.checksum}"

    @property
    def result_image_name(self) -> str:
        return self.cache_name


    def run(
        self,
        cache_dir: Union[str, pl.Path] = None,
        locally: bool = False
    ):
        """
        Perform the deployment step by running the shell script. It also allows perform it inside the docker.

        :param cache_dir: Path to the directory which will be used as cache. It is passed to the shell script as a first
            argument, so it it possible to save/reuse some intermediate result in the script. It may be useful if
            deployment has to be done on some CI/CD machine, which is new on each run. When deployment step operates in
            docker, then it caches the whole result image by using 'docker save'. On the second run, the step can
            load the image from this cached file without rebuilding.
        """

        if locally or not self.in_docker:
            # Choose the shell according to the operation system.
            if type(self).SCRIPT_PATH.suffix == ".ps1":
                shell = "powershell"
            else:
                shell = shutil.which("bash")

            command = [shell, str(type(self).SCRIPT_PATH)]

            # If cache directory is presented, then we pass it as an additional argument to the
            # script, so it can use the cache too.
            if cache_dir:
                command.append(str(pl.Path(cache_dir)))

            # Run the script in previously chosen shell.
            subprocess.check_call(
                command,
            )
            return

        self.run_in_docker(
            cache_dir=cache_dir
        )

    def run_in_docker(
        self,
        cache_dir: Union[str, pl.Path] = None,

    ):
        """
        This function does the same deployment but inside the docker.
        :param base_docker_image: Name of the base docker image. The shell script will be executed inside its container.
        :param result_image_name: The name of the result image.
        :param architecture: Type of the processor architecture. Docker can use emulation to support different platforms.
        :param cache_dir: The cache directory. the same as in the main functions.
        """

        result_image_name = self.result_image_name

        # Before the build, check if there is already an image with the same name. The name contains the checksum
        # of all files which are used in it, so the name identity also guarantees the content identity.
        output = (
            subprocess.check_output(["docker", "images", "-q", result_image_name])
            .decode()
            .strip()
        )

        if output:
            # The image already exists, skip the build.
            logging.info(
                f"Image '{result_image_name}' already exists, skip the build and reuse it."
            )
            return

        save_to_cache = False

        # If cache directory is specified, then check if the image file is already there and we can reuse it.
        if cache_dir:
            cache_dir = pl.Path(cache_dir)
            cached_image_path = cache_dir / result_image_name
            if cached_image_path.is_file():
                logging.info(
                    f"Cached image {result_image_name} file for the deployment step '{self.name}' has been found, "
                    f"loading and reusing it instead of building."
                )
                subprocess.check_call(
                    ["docker", "load", "-i", str(cached_image_path)]
                )
                return
            else:
                # Cache is used but there is no suitable image file. Set the flag to signal that the built
                # image has to be saved to the cache.
                save_to_cache = True

        logging.info(
            f"Build image '{result_image_name}' from base image '{self.base_docker_image}' "
            f"for the deployment step '{self.name}'."
        )

        # Create the image.
        # Instead of using the 'docker build', just create the image from 'docker commit' from the container.

        container_root_path = pl.Path("/scalyr-agent-2")

        # All files, which are used in the build have to be mapped to the docker container.
        volumes_mappings = []
        for used_path in self._get_used_files():
            rel_used_path = pl.Path(used_path).relative_to(__SOURCE_ROOT__)
            abs_host_path = __SOURCE_ROOT__ / rel_used_path
            abs_container_path = container_root_path / rel_used_path
            volumes_mappings.extend(["-v", f"{abs_host_path}:{abs_container_path}"])

        # Map the script's path to the docker.
        container_prepare_env_script_path = pl.Path(
            container_root_path,
            pl.Path(type(self).SCRIPT_PATH).relative_to(
                __SOURCE_ROOT__
            ),
        )

        container_name = result_image_name

        # Remove if such container exists.
        subprocess.check_call(["docker", "rm", "-f", container_name])

        # Create container and run the script in it.
        subprocess.check_call(
            [
                "docker",
                "run",
                "--platform",
                self.architecture.as_docker_platform.value,
                "-i",
                "--name",
                container_name,
                *volumes_mappings,
                self.base_docker_image,
                str(container_prepare_env_script_path),
            ],
        )

        # Save the current state of the container into image.
        subprocess.check_call(["docker", "commit", container_name, result_image_name])

        # Save image if caching is enabled.
        if cache_dir and save_to_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_image_path = cache_dir / result_image_name
            logging.info(f"Saving image '{result_image_name}' file for the deployment step {self.name} into cache.")
            with cached_image_path.open("wb") as f:
                subprocess.check_call(["docker", "save", result_image_name], stdout=f)

    def _get_used_files(self) -> List[pl.Path]:
        """
            Get the list of all files which are used in the deployment.
            This is basically needed to calculate their checksum.
        """

        # The shell script is also has to be included.
        used_files = [type(self).SCRIPT_PATH]

        # Since the list of used files can also contain directories, look for them and
        # include all files inside them recursively.
        for path in type(self).USED_FILES:
            path = pl.Path(path)

            # match glob against source code root and include all matched paths.
            relative_path = path.relative_to(__SOURCE_ROOT__)
            found = list(__SOURCE_ROOT__.glob(str(relative_path)))

            used_files.extend(found)

        used_files = sorted(used_files)
        return used_files

    def get_used_files_checksum(
            self,
            additional_seed: str = None,
    ):
        """
        Calculate the sha256 checksum of all files which are used in the deployment.
        """

        used_files = self._get_used_files()

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_path in used_files:
            file_path = pl.Path(file_path)
            sha256.update(str(file_path.relative_to(__SOURCE_ROOT__)).encode())
            sha256.update(str(file_path.stat().st_mode).encode())
            sha256.update(file_path.read_bytes())

        if additional_seed:
            sha256.update(additional_seed.encode())
        return sha256.hexdigest()


# @dataclasses.dataclass
# class Deployment:
#     """
#     The abstraction that defines some desired state of the environment that has to be achieved by performing some set of
#         deployment steps (:py:class:`DeploymentStep`).
#     """
#     ALL_DEPLOYMENTS: ClassVar[Dict[str, 'Deployment']] = {}
#
#     name: str
#     steps: List[DeploymentStep]
#
#     @staticmethod
#     def create_deployment(
#             name: str,
#             steps: List[DeploymentStep]
#     ):
#         """
#         Create the deployment with given name and deployment steps.
#         :param name: Name of the deployment. All deployment are stored in the globally available class attribute
#             collection, so their names has to unique.
#         :return: New deployment object.
#         """
#
#         if name in Deployment.ALL_DEPLOYMENTS:
#             raise ValueError(f"The deployment with name {name} already exists.")
#
#         deployment = Deployment(
#             name=name,
#             steps=steps
#         )
#
#         # Save created deployment in the global deployments collections.
#         Deployment.ALL_DEPLOYMENTS[deployment.name] = deployment
#
#         return deployment

class Deployment:
    ALL_DEPLOYMENTS: Dict[str, 'Deployment'] = {}

    def __init__(
            self,
            name: str,
            step_classes: List[Type[DeploymentStep]],
            architecture: constants.Architecture,
            base_docker_image: str = None
    ):
        self.name = name
        self.architecture = architecture
        self.steps = []

        new_step_classes = step_classes[:]
        first_step_cls = new_step_classes.pop(0)

        previous_step = first_step_cls(
            architecture=architecture,
            base_docker_image=base_docker_image
        )
        self.steps.append(previous_step)

        for step_cls in new_step_classes:
            step = step_cls(
                architecture=architecture,
                previous_step=previous_step,
            )
            previous_step = step
            self.steps.append(step)

        type(self).ALL_DEPLOYMENTS[self.name] = self


    @property
    def result_image_name(self) -> Optional[str]:
        return self.steps[-1].result_image_name.lower()

    def deploy(
            self,
            cache_dir: pl.Path = None,
            locally: bool = False
    ):


        for step in self.steps:

            if cache_dir:
                step_cache_path = cache_dir / step.cache_name
            else:
                step_cache_path = None

            step.run(
                cache_dir=step_cache_path,
                locally=locally,
            )



_SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployer_scripts"


class InstallPythonStep(DeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "install_python_and_ruby.sh"


# Paths to the helper files that may be helpful for the main deployment script.
_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS = [
    # bash library that provides a simple caching logic.
    __SOURCE_ROOT__ / _SCRIPTS_DIR_PATH / "cache_lib.sh"
]

# Glob that has to match all requirement files that are needed for the agent build.
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_DIR / "requirement-files" / "*.txt"


class InstallBuildRequirementsStep(DeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_build_environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


class InstallTestRequirementsDeploymentStep(DeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy-dev-environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH, __SOURCE_ROOT__ / "dev-requirements.txt"
    ]


class InstallWindowsBuilderToolsStep(DeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1"
    USED_FILES = used_files = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


COMMON_TEST_DEPLOYMENT = Deployment(
    name="test_environment",
    architecture=constants.Architecture.X86_64,
    step_classes=[InstallBuildRequirementsStep]
)


# LINUX_PACKAGE_BUILDER_DEPLOYMENT = Deployment.create_deployment(
#     name="linux_package_builder",
#     steps=[INSTALL_PYTHON_STEP, INSTALL_BUILD_REQUIREMENTS_STEP],
# )


class LinuxPackageBuilderDeployment(Deployment):
    pass



# class DeploymentSpec:
#     """
#     The specification of the deployment. It has all needed specifics, for example architecture type or
#         docker image, to perform the actual deployment.
#     """
#     @dataclasses.dataclass
#     class DeploymentStepSpec:
#         """
#         Also the specification but for the inner deployment steps. Each
#         """
#         step: DeploymentStep
#         architecture: constants.Architecture
#         step_checksum: str
#         base_docker_image: Optional[str] = None
#         previous_step_spec: Optional['DeploymentSpec.DeploymentStepSpec'] = None
#
#         @property
#         def in_docker(self) -> bool:
#             """
#             Flag that signals that the deployment step is meant to be performed in docker.
#             """
#             return self.base_docker_image is not None
#
#         @property
#         def unique_name(self) -> str:
#             """
#             Create name for the step. It has to contain all specific information about the step,
#             so it can be used as unique cache key.
#             """
#
#             name = self.step.name
#
#             #
#             if self.previous_step_spec:
#                 name = f"{name}_{self.previous_step_spec.step.name}"
#
#             name = f"{name}_{self.architecture.value}"
#
#             # If its a docker deployment, then add the docker image to the name
#             if self.in_docker:
#                 image_suffix = self.base_docker_image.replace(":", "_")
#                 name = f"{name}_{image_suffix}"
#
#             name = f"{name}_{self.step_checksum}"
#
#             return name
#
#     ALL_DEPLOYMENT_SPECS: Dict[str, 'DeploymentSpec'] = {}
#
#     def __init__(
#             self,
#             deployment: Deployment,
#             architecture: constants.Architecture = None,
#             base_docker_image: str = None,
#     ):
#         self.deployment = deployment
#         self.architecture = architecture
#         self.base_docker_image = base_docker_image
#         self.all_deployment_step_specs = []
#
#         previous_step_checksum = None
#         previous_step_spec = None
#         for step in self.deployment.steps:
#             step_spec = DeploymentSpec.DeploymentStepSpec(
#                 step=step,
#                 architecture=self.architecture,
#                 step_checksum=step.get_used_files_checksum(
#                     additional_seed=previous_step_checksum
#                 ),
#                 base_docker_image=base_docker_image,
#                 previous_step_spec=previous_step_spec,
#             )
#
#             previous_step_checksum = step_spec.step_checksum
#             previous_step_spec = step_spec
#
#             self.all_deployment_step_specs.append(step_spec)
#
#     @property
#     def result_image_name(self) -> Optional[str]:
#         if self.in_docker:
#             return self.all_deployment_step_specs[-1].unique_name
#
#     @property
#     def name(self) -> str:
#         name = f"{self.deployment.name}_{self.architecture.value}"
#         if self.base_docker_image:
#             image_name = self.base_docker_image.replace(":", "_")
#             name = f"{name}_{image_name}"
#
#         return name
#
#     @property
#     def result_docker_image(self) -> Optional[str]:
#         if self.in_docker:
#             return self.deployment.steps[-1].name
#
#     @property
#     def in_docker(self) -> bool:
#         return self.base_docker_image is not None
#
#     def deploy(
#             self,
#             cache_dir: Union[str, pl.Path] = None
#     ):
#         previous_base_docker_image = self.base_docker_image
#
#         for step_spec in self.all_deployment_step_specs:
#             logging.info(f"Perform the deployment step '{step_spec.step.name}'.")
#             if cache_dir:
#
#                 # create separate cache folder for this deployment, to avoid collisions with other deployments.
#                 step_cache_dir_path = pl.Path(cache_dir) / step_spec.unique_name
#
#                 logging.info(f"Using cache dir '{step_cache_dir_path}'.")
#             else:
#                 step_cache_dir_path = None
#
#             if self.in_docker:
#                 step_spec.step.run_in_docker(
#                     base_docker_image=previous_base_docker_image,
#                     result_image_name=step_spec.unique_name,
#                     architecture=self.architecture,
#                     cache_dir=step_cache_dir_path
#                 )
#                 previous_base_docker_image = step_spec.unique_name
#             else:
#                 step_spec.step.run(
#                     cache_dir=step_cache_dir_path
#                 )
#
#     @staticmethod
#     def create_new_deployment_spec(
#             architecture: constants.Architecture,
#             deployment: Deployment,
#             base_docker_image: str = None
#     ) -> 'DeploymentSpec':
#
#         spec = DeploymentSpec(
#             deployment=deployment,
#             architecture=architecture,
#             base_docker_image=base_docker_image
#         )
#
#         if spec.name not in DeploymentSpec.ALL_DEPLOYMENT_SPECS:
#             DeploymentSpec.ALL_DEPLOYMENT_SPECS[spec.name] = spec
#         else:
#             spec = DeploymentSpec.ALL_DEPLOYMENT_SPECS[spec.name]
#
#         return spec
#
#
# _SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployer_scripts"
#
# # This deployer is used in the package building.
# # Since we use frozen binaries, it is important to produce the binary using the earliest glibc possible,
# # to achieve binary compatibility with more operating systems.
# INSTALL_PYTHON_STEP = DeploymentStep(
#     name="install_python",
#     deployment_script_path=_SCRIPTS_DIR_PATH / "install_python_and_ruby.sh"
# )
#
# # Paths to the helper files that may be helpful for the main deployment script.
# _HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS = [
#     # bash library that provides a simple caching logic.
#     __SOURCE_ROOT__ / _SCRIPTS_DIR_PATH / "cache_lib.sh"
# ]
#
# # Glob that has to match all requirement files that are needed for the agent build.
# _AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_DIR / "requirement-files" / "*.txt"
#
# # Deployer to install all agent's Python dependencies. This is not included to the previous 'python' deployer.
# # because building Python from source is a very long process, and its better to avoid unnecessary rebuilding when
# # there is just something changed in agent requirements.
# INSTALL_BUILD_REQUIREMENTS_STEP = DeploymentStep(
#     name="install_build_environment",
#     deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_build_environment.sh",
#     used_files=[
#         *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
#         _AGENT_REQUIREMENT_FILES_PATH
#     ],
# )
#
# # The deployer which prepares a build environment for the windows package.
# # For now, it just installs the WIX toolset, which is needed to create msi packages.
# INSTALL_WINDOWS_BUILDER_TOOLS_STEP = DeploymentStep(
#     name="install_windows_builder_tools_step",
#     deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1",
#     used_files=[
#         *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
#         _AGENT_REQUIREMENT_FILES_PATH
#     ],
# )
#
#
# # The deployer for the test environment. It is built upon previous 'build-environment' deployer, but it also
# # install all test dependencies. It is also created as a separate deployer because PyInstaller, (frozen binary tools),
# # tends to include unneeded packages into the frozen binary, which increases its size.
# INSTALL_TEST_REQUIREMENT_STEP = DeploymentStep(
#     name="install_test_environment",
#     deployment_script_path=_SCRIPTS_DIR_PATH / "deploy-dev-environment.sh",
#     used_files=[
#         *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
#         _AGENT_REQUIREMENT_FILES_PATH, __SOURCE_ROOT__ / "dev-requirements.txt"],
# )
#
#
# LINUX_PACKAGE_BUILDER_DEPLOYMENT = Deployment.create_deployment(
#     name="linux_package_builder",
#     steps=[INSTALL_PYTHON_STEP, INSTALL_BUILD_REQUIREMENTS_STEP],
# )
#
#
# WINDOWS_PACKAGE_BUILDER_DEPLOYMENT = Deployment.create_deployment(
#     name="windows_package_builder",
#     steps=[INSTALL_WINDOWS_BUILDER_TOOLS_STEP, INSTALL_BUILD_REQUIREMENTS_STEP]
# )
#
# LINUX_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT = Deployment.create_deployment(
#     name="linux_package_tests_environment",
#     steps=[*LINUX_PACKAGE_BUILDER_DEPLOYMENT.steps, INSTALL_TEST_REQUIREMENT_STEP]
# )
#
# WINDOWS_PACKAGE_TESTS_ENVIRONMENT_DEPLOYMENT = Deployment.create_deployment(
#     name="windows_package_tests_environment",
#     steps=[INSTALL_TEST_REQUIREMENT_STEP]
# )
#
# COMMON_TEST_ENVIRONMENT = Deployment.create_deployment(
#     name="test_environment",
#     steps=[INSTALL_TEST_REQUIREMENT_STEP]
# )