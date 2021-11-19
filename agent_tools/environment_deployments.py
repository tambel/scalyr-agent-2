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
# It contains a set of pre-defined deployments. The whole purpose of deployers is to
# provide unified and also "CI/CD platform agnostic" way of creating environments where agent packages are built.

import abc
import pathlib as pl
import shlex
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
from agent_tools import build_in_docker


class DeploymentStep:
    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.

    """

    # Special collection where all created deployment steps are stored. All of the a saved with unique name as key, so
    # it is possible to find any deployment step by its names. The ability to find needed deployment step by its name is
    # crucial if we want to run it on the CI/CD.
    ALL_DEPLOYMENT_STEPS: Dict[str, 'DeploymentStep'] = {}

    # Set of files that are somehow used during the step. Needed to calculate the checksum of the whole step, so it can
    # be used as cache key.
    USED_FILES: List[pl.Path] = []

    def __init__(
            self,
            architecture: constants.Architecture,
            previous_step: Union[str, 'DeploymentStep'] = None
    ):
        """
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        self.architecture = architecture

        if isinstance(previous_step, DeploymentStep):
            # The previous step is specified.
            # The base docker image is a result image of the previous step.
            self.base_docker_image = previous_step.result_image_name
            self.previous_step = previous_step
        elif isinstance(previous_step, str):
            # The previous step isn't specified, but it is just a base docker image.
            self.base_docker_image = previous_step
            self.previous_step = None
        else:
            # the previous step is not specified.
            self.base_docker_image = None
            self.previous_step = None

        # Add this instance to the global collection of all deployment steps.
        type(self).ALL_DEPLOYMENT_STEPS[self.name] = self

        self.used_files = self._init_used_files(type(self).USED_FILES)

    @staticmethod
    def _init_used_files(file_globs: List[pl.Path]):
        """
            Get the list of all files which are used in the deployment.
            This is basically needed to calculate their checksum.
        """
        used_files = []

        for path in file_globs:
            path = pl.Path(path)

            # match glob against source code root and include all matched paths.
            relative_path = path.relative_to(__SOURCE_ROOT__)
            found = list(__SOURCE_ROOT__.glob(str(relative_path)))

            used_files.extend(found)

        return sorted(list(set(used_files)))


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
    def initial_docker_image(self) -> str:
        """
        Name of the docker image of the most parent step. If step is not performed in the docker, returns None,
            otherwise it has to be the name of some public image.
        This is needed for the step's unique name to be distinguishable from other instances of the same step but with
            different base images, for example centos:6 and centos:7
        """
        if not self.previous_step:
            return self.base_docker_image

        return self.previous_step.initial_docker_image

    @property
    def cache_key(self) -> str:
        """
        Unique cache key based on the name of the step and on the content of used files.
        """
        return f"{self.unique_name}_{self.checksum}"

    @property
    def result_image_name(self) -> str:
        """
        The name of the result docker image, just the same as cache key.
        """
        return self.cache_key

    @property
    def in_docker(self) -> bool:
        """
        Whether this step has to be performed in docker or not.
        """
        return self.initial_docker_image is not None

    @property
    def checksum(self) -> str:
        """
        The checksum of the step. It is based on content of the used files + checksum of the previous step.
        """

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_glob in self.used_files:
            for file_path in file_glob.parent.glob(file_glob.name):
                sha256.update(str(file_path.relative_to(__SOURCE_ROOT__)).encode())
                sha256.update(str(file_path.stat().st_mode).encode())
                sha256.update(file_path.read_bytes())

        # Also include the checksum of the previous step.
        if self.previous_step:
            sha256.update(self.previous_step.checksum.encode())

        return sha256.hexdigest()

    def run(
            self,
            cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.

        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it.
        :param locally: A special flag that forces a step to be performed locally on the current system, even
            if it meant to be performed inside docker. This is needed to avoid the loop when the step is already in the
            docker.
        """

        if self.in_docker:
            self.run_in_docker(
                cache_dir=cache_dir
            )
        else:
            self._run_locally(
                cache_dir=cache_dir
            )

    def run_in_docker(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        This function does the same deployment but inside the docker.
        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it. In case of docker, the whole result image of the step will be cached.
        """

        # Before the build, check if there is already an image with the same name. The name contains the checksum
        # of all files which are used in it, so the name identity also guarantees the content identity.
        output = (
            subprocess.check_output(["docker", "images", "-q", self.result_image_name])
            .decode()
            .strip()
        )

        if output:
            # The image already exists, skip the build.
            logging.info(
                f"Image '{self.result_image_name}' already exists, skip the build and reuse it."
            )
            return

        save_to_cache = False

        # If cache directory is specified, then check if the image file is already there and we can reuse it.
        if cache_dir:
            cache_dir = pl.Path(cache_dir)
            cached_image_path = cache_dir / self.result_image_name
            if cached_image_path.is_file():
                logging.info(
                    f"Cached image {self.result_image_name} file for the deployment step '{self.name}' has been found, "
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
            f"Build image '{self.result_image_name}' from base image '{self.base_docker_image}' "
            f"for the deployment step '{self.name}'."
        )

        self._run_in_docker()

        if cache_dir and save_to_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_image_path = cache_dir / self.result_image_name
            logging.info(f"Saving image '{self.result_image_name}' file for the deployment step {self.name} into cache.")
            with cached_image_path.open("wb") as f:
                subprocess.check_call(["docker", "save", self.result_image_name], stdout=f)

    @abc.abstractmethod
    def _run_locally(
            self,
            cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run step locally. This has to be implemented in children classes.
        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it.
        """
        pass

    @abc.abstractmethod
    def _run_in_docker(
            self,
            cache_dir: Union[str, pl.Path] = None,
            locally: bool = False
    ):
        """
        Run step in docker. This has to be implemented in children classes.
        :param cache_dir: Path of the cache directory.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """
        pass


class DockerFileDeploymentStep(DeploymentStep):
    """
    The deployment step which actions are defined in the Dockerfile. A implies, can be performed only in docker.
    """

    # Path the dockerfile.
    DOCKERFILE_PATH: pl.Path

    def __init__(
            self,
            architecture: constants.Architecture,
            previous_step: Union[str, 'DeploymentStep'] = None
    ):
        super(DockerFileDeploymentStep, self).__init__(
            architecture=architecture,
            previous_step=previous_step
        )

        # Also add dockerfile to the used file collection, so it is included to the checksum calculation.
        self.used_files = self._init_used_files(
            self.used_files + [type(self).DOCKERFILE_PATH]
        )

    @property
    def in_docker(self) -> bool:
        # This step is in docker by definition.
        return True

    def _run_locally(
            self,
            cache_dir: Union[str, pl.Path] = None,
    ):
        # This step is in docker by definition.
        raise RuntimeError("The docker based step can not be performed locally.")

    def _run_in_docker(
            self,
            cache_dir: Union[str, pl.Path] = None,
            locally: bool = False
    ):
        """
        Perform the actual build by calling docker build with specified dockerfile and other options.
        :param cache_dir: Path of the cache directory.
        :param locally: This is ignored, the dockerfile based step can not be performed locally.
        """
        build_in_docker.run_docker_build(
            architecture=self.architecture,
            image_name=self.result_image_name,
            dockerfile_path=type(self).DOCKERFILE_PATH,
            build_context_path=type(self).DOCKERFILE_PATH.parent
        )


class ShellScriptDeploymentStep(DeploymentStep):
    """
    The deployment step class which is a wrapper around some shell script.
    """

    # Pat hto  the script file that has to be executed during the step.
    SCRIPT_PATH: pl.Path

    def __init__(
            self,
            architecture: constants.Architecture,
            previous_step: Union[str, 'DeploymentStep'] = None
    ):
        super(ShellScriptDeploymentStep, self).__init__(
            architecture=architecture,
            previous_step=previous_step
        )

        # Also add script to the used file collection, so it is included to the checksum calculation.
        self.used_files = self._init_used_files(
            self.used_files + [type(self).SCRIPT_PATH]
        )

    def _get_command(
            self,
            source_path: pl.Path,
            cache_dir: Union[str, pl.Path] = None,

    ) -> str:
        """
        Create string with the shell command that has to execute the shell script.
            Optionally also adds cache path to the shell script as additional argument.
        :param source_path: PAth to the source root. Since this coommand can be executed in docker within
            different filesystem, then the source root also has to be different.
        :param cache_dir: Path to the cache dir.
        :return: String with shell command that can be executed to needed shell.
        """

        # Determine deeded shell interpreter.
        if type(self).SCRIPT_PATH.suffix == ".ps1":
            shell = "powershell"
        else:
            shell = shutil.which("bash")

        # Create final absolute path to the script.
        final_script_path = source_path / type(self).SCRIPT_PATH.relative_to(__SOURCE_ROOT__)

        command = [shell, str(final_script_path)]

        # If cache directory is presented, then we pass it as an additional argument to the
        # script, so it can use the cache too.
        if cache_dir:
            command.append(str(pl.Path(cache_dir)))

        return shlex.join(command)

    def _run_locally(
            self,
            cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run step locally by running the script on current system.
        :param cache_dir: Path of the cache directory. If specified, then the script may save or reuse some intermediate
            result using it.
        """
        subprocess.check_call(
            self._get_command(
                source_path=__SOURCE_ROOT__,
                cache_dir=cache_dir
            ),
            shell=True
        )

    def _run_in_docker(
            self,
            cache_dir: Union[str, pl.Path] = None,
            locally: bool = False
    ):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_tools.build_in_docker' module,
        that allows to execute custom command inside docker by using 'docker build' command. It differs from running
        just in the container because we can benefit from the docker caching mechanism.
        :param cache_dir: Path of the cache directory.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """

        # Since we used 'docker build' instead of 'docker run', we can not just mount files, that are used in this step.
        # Instead of that, we'll create intermediate image with all files and use it as base image.

        # To create an intermediate image, first we create container, put all needed files and commit it.

        mounted_container_root_path = pl.Path("/scalyr-agent-2-mount")
        # All files, which are used in the build have to be mapped to the docker container filesystem.
        volumes_mappings = []
        for used_path in self.used_files:
            rel_used_path = pl.Path(used_path).relative_to(__SOURCE_ROOT__)
            abs_host_path = __SOURCE_ROOT__ / rel_used_path
            abs_container_path = mounted_container_root_path / rel_used_path
            volumes_mappings.extend(["-v", f"{abs_host_path}:{abs_container_path}"])

        intermediate_image_name = f"{self.result_image_name}-intermediate"

        # Remove if such intermediate container exists.
        subprocess.check_call(["docker", "rm", "-f", intermediate_image_name])

        try:
            # Create container and copy all mounted files to the final path inside the container.
            # This is needed because if we just use mounted path, files become empty after container stops.
            # There has to be some workaround by plying with mount typed, but for now the current approach has to be
            # fine too.
            subprocess.check_call(
                [
                    "docker",
                    "run",
                    "--platform",
                    self.architecture.as_docker_platform.value,
                    "-i",
                    "--name",
                    intermediate_image_name,
                    *volumes_mappings,
                    self.base_docker_image,
                    "/bin/bash",
                    "-c",
                    f"cp -a {mounted_container_root_path}/. /scalyr-agent-2"
                ],
            )

            # Commit intermediate container as image.
            subprocess.check_call(["docker", "commit", intermediate_image_name, intermediate_image_name])

            # Get command that has to run shell script.
            command = self._get_command(
                source_path=pl.Path("/scalyr-agent-2"),
                cache_dir=cache_dir
            )

            # Run command in the previously created intermediate image.
            build_in_docker.build_stage(
                command=command,
                stage_name="step-build",
                architecture=self.architecture,
                image_name=self.result_image_name,
                base_image_name=intermediate_image_name,
            )

        finally:
            # Remove intermediate container and image.
            subprocess.check_call(["docker", "rm", "-f", intermediate_image_name])
            subprocess.check_call(["docker", "image ", "rm", "-f", intermediate_image_name])


class Deployment:
    """
    Abstraction which represents some final desired state of the environment which is defined by set of steps, which are
    instances of the :py:class:`DeploymentStep`
    """

    # Special collection where all created deployments are stored. All of the a saved with unique name as key, so
    # it is possible to find any deployment by its names. The ability to find needed deployment step by its name is
    # crucial if we want to run it on the CI/CD.
    ALL_DEPLOYMENTS: Dict[str, 'Deployment'] = {}

    def __init__(
            self,
            name: str,
            step_classes: List[Type[DeploymentStep]],
            architecture: constants.Architecture,
            base_docker_image: str = None
    ):
        """
        :param name: Name of the deployment. Must be unique for the whole project.
        :param step_classes: List of step classes. All those steps classes will be instantiated
            by using current specifics.
        :param architecture: Architecture of the machine where deployment and its steps has to be performed.
        :param base_docker_image: Name of the docker image, if the deployment and all its steps has to be performed
            inside that docker image.
        """
        self.name = name
        self.architecture = architecture

        # List with instantiated steps.
        self.steps = []

        # If docker image is used that is has to be passed as previous step for the first step.
        previous_step = base_docker_image

        for step_cls in step_classes:
            step = step_cls(
                architecture=architecture,
                # specify previous step for the current step.
                previous_step=previous_step,
            )
            previous_step = step
            self.steps.append(step)

        # Add this instance to the global collection of all deployments.
        type(self).ALL_DEPLOYMENTS[self.name] = self

    @property
    def in_docker(self) -> bool:
        """
        Flag that shows whether this deployment has to be performed in docker or not.
        """
        # If its first step is in docker that the deployment also in docker.
        return self.steps[0].in_docker

    @property
    def result_image_name(self) -> Optional[str]:
        """
        The name of the result image of the whole deployment if it has to be performed in docker. It's, logically,
        just a result image name of the last step.
        """
        return self.steps[-1].result_image_name.lower()

    def deploy(
            self,
            cache_dir: pl.Path = None,
    ):
        """
        Perform the deployment by running all deployment steps.

        :param cache_dir: Cache directory. If specified, all steps of the deployment will use it to
            save their results in it.
        :return:
        """

        for step in self.steps:

            # If cache is specified, then create separate sub-folder in it for each step.
            # NOTE: Those sub-folders are used by our special Github-Actions action that caches all such sub-folders to
            # the Github Actions cache. See more in ".github/actions/perform-deployment"
            if cache_dir:
                step_cache_path = cache_dir / step.cache_key
            else:
                step_cache_path = None

            step.run(
                cache_dir=step_cache_path,
            )


_SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployment_steps"


# Docker based step that build image with Python and other needed tools.
# The specific of this Python, is that it is build against very early version of glibc (2.12), so the statically bundled
# frozen binary has to work starting from centos:6
class InstallPythonStep(DockerFileDeploymentStep):
    USED_FILES = [_SCRIPTS_DIR_PATH / "build-python" / "*"]
    DOCKERFILE_PATH = _SCRIPTS_DIR_PATH / "build-python" / "Dockerfile"


# Paths to the helper files that may be helpful for the main deployment script.
_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS = [
    # bash library that provides a simple caching logic.
    __SOURCE_ROOT__ / _SCRIPTS_DIR_PATH / "cache_lib.sh"
]

# Glob that has to match all requirement files that are needed for the agent build.
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_DIR / "requirement-files" / "*.txt"


# Step that rn small script which install all needed agent build requirements from requirement files.
class InstallBuildRequirementsStep(ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_build_environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


# Step that rn small script which installs requirements from the test/dev environment.
class InstallTestRequirementsDeploymentStep(ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy-dev-environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH, __SOURCE_ROOT__ / "dev-requirements.txt"
    ]


# Step that prepare all tools that are needed for the windows package build.
# For now it just a WIX toolset, which is needed to  create msi packages.
class InstallWindowsBuilderToolsStep(ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1"
    USED_FILES = used_files = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


# Common test environment. Just installs all dev environment to the current system.
# Used by Github Actions CI/CD.
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
# _SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployment_steps"
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