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

import argparse
import pathlib as pl
import platform
import shutil
import subprocess
import hashlib
import logging
from typing import Union, Optional, List, Dict

__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent.parent
_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"


class EnvironmentDeployer:
    """
    Base abstraction of the deployer.
    """

    def __init__(
            self,
            name: str,
            deployment_script_path: Union[str, pl.Path],
            used_files: list = None,
            base_deployer: Optional['EnvironmentDeployer'] = None,
    ):
        self._name = name
        self._deployment_script_path = deployment_script_path
        self._used_files = used_files or []
        self._base_deployer = base_deployer

        self._used_files_checksum: Optional[str] = None

    @property
    def name(self):
        return self._name

    @property
    def base_deployer(self) -> Optional['EnvironmentDeployer']:
        return self._base_deployer


    def deploy(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """

        # Prepare the environment on the current system.

        # Choose the shell according to the operation system.
        if self._deployment_script_path.suffix == ".ps1":
            shell = "powershell"
        else:
            shell = shutil.which("bash")

        command = [shell, str(self._deployment_script_path)]

        # If cache directory is presented, then we pass it as an additional argument to the
        # 'prepare build environment' script, so it can use the cache too.
        if cache_dir:
            command.append(str(pl.Path(cache_dir)))

        # Run the 'prepare build environment' script in previously chosen shell.
        subprocess.check_call(
            command,
        )

    def deploy_in_docker(
        self,
        base_docker_image: str,
        cache_dir: Union[str, pl.Path] = None,

    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """
        # Instead of preparing the build environment on the current system, create the docker image and prepare the
        # build environment there. If cache directory is specified, then the docker image will be serialized to the
        # file and that file will be stored in the cache.

        if self._base_deployer:
            self._base_deployer.deploy_in_docker(
                base_docker_image=base_docker_image,
                cache_dir=cache_dir,
            )

        # Get the name of the builder image.
        image_name = self.get_image_name(
            base_docker_image=base_docker_image
        )

        # Before the build, check if there is already an image with the same name. The name contains the checksum
        # of all files which are used in it, so the name identity also guarantees the content identity.
        output = (
            subprocess.check_output(["docker", "images", "-q", image_name])
            .decode()
            .strip()
        )

        if output:
            # The image already exists, skip the build.
            logging.info(
                f"Image '{image_name}' already exists, skip the build and reuse it."
            )
            return

        save_to_cache = False

        # If cache directory is specified, then check if the image file is already there and we can reuse it.
        if cache_dir:
            cache_dir = pl.Path(cache_dir)
            cached_image_path = cache_dir / image_name
            if cached_image_path.is_file():
                logging.info(
                    "Cached image file has been found, loading and reusing it instead of building."
                )
                subprocess.check_call(
                    ["docker", "load", "-i", str(cached_image_path)]
                )
                return
            else:
                # Cache is used but there is no suitable image file. Set the flag to signal that the built
                # image has to be saved to the cache.
                save_to_cache = True

        logging.info(f"Build image '{image_name}'")

        # Create the builder image.
        # Instead of using the 'docker build', just create the image from 'docker commit' from the container.

        container_root_path = pl.Path("/scalyr-agent-2")

        # All files, which are used in the build have to be mapped to the docker container.
        volumes_mappings = []
        for used_path in self._get_used_files():
            rel_used_path = pl.Path(used_path).relative_to(__SOURCE_ROOT__)
            abs_host_path = __SOURCE_ROOT__ / rel_used_path
            abs_container_path = container_root_path / rel_used_path
            volumes_mappings.extend(["-v", f"{abs_host_path}:{abs_container_path}"])

        # Map the 'prepare environment' script's path to the docker.
        container_prepare_env_script_path = pl.Path(
            container_root_path,
            pl.Path(self._deployment_script_path).relative_to(
                __SOURCE_ROOT__
            ),
        )

        container_name = self.get_image_name(base_docker_image)

        # Remove if such container exists.
        subprocess.check_call(["docker", "rm", "-f", container_name])

        if self._base_deployer:
            final_base_image = self._base_deployer.get_image_name(
                base_docker_image=base_docker_image
            )
        else:
            final_base_image = base_docker_image

        # Create container and run the 'prepare environment' script in it.
        subprocess.check_call(
            [
                "docker",
                "run",
                "-i",
                "--name",
                container_name,
                *volumes_mappings,
                final_base_image,
                str(container_prepare_env_script_path),
            ]
        )

        # Save the current state of the container into image.
        subprocess.check_call(["docker", "commit", container_name, image_name])

        # Save image if caching is enabled.
        if cache_dir and save_to_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_image_path = cache_dir / image_name
            logging.info(f"Saving '{image_name}' image file into cache.")
            with cached_image_path.open("wb") as f:
                subprocess.check_call(["docker", "save", image_name], stdout=f)


    def get_image_name(self, base_docker_image: str):

        image_name = base_docker_image.replace(":", "_")
        return f"scalyr-build-deployer-{self._name}-{self.get_used_files_checksum()}-{image_name}".lower()


    def _get_used_files(self) -> List[pl.Path]:
        """
            Get the list of all files which are used in the deployment.
            This is basically needed to calculate their checksum.
        """

        def get_dir_files(dir_path: pl.Path):
            # ignore those directories.
            if dir_path.name == "__pycache__":
                return []

            result = []
            for child_path in dir_path.iterdir():
                if child_path.is_dir():
                    result.extend(get_dir_files(child_path))
                else:
                    result.append(child_path)

            return result

        used_files = []

        # The shell script is also has to be included.
        used_files.append(self._deployment_script_path)

        # Since the list of used files can also contain directories, look for them and
        # include all files inside them recursively.
        for path in self._used_files:
            path = pl.Path(path)
            if path.is_dir():
                used_files.extend(get_dir_files(path))
            else:
                used_files.append(path)

        return used_files

    def get_used_files_checksum(self):
        """
        Calculate the sha256 checksum of all files which are used in the deployment.
        """

        if self._used_files_checksum:
            return self._used_files_checksum

        used_files = self._get_used_files()

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_path in used_files:
            file_path = pl.Path(file_path)
            sha256.update(str(file_path).encode())
            sha256.update(str(file_path.stat().st_mode).encode())
            sha256.update(file_path.read_bytes())

        self._used_files_checksum = sha256.hexdigest()
        return self._used_files_checksum


class BaseEnvironmentDeployer(EnvironmentDeployer):
    FILES_USED_IN_DEPLOYMENT = [
        _AGENT_BUILD_DIR / "requirements.txt",
        _AGENT_BUILD_DIR / "monitors_requirements.txt",
        __SOURCE_ROOT__ / "dev-requirements.txt",
        __SOURCE_ROOT__ / "benchmarks/micro/requirements-compression-algorithms.txt",
    ]


if platform.system() != "Windows":
    base_environment_script_path = __PARENT_DIR__ / "deploy_base_environment.sh"
else:
    base_environment_script_path = __PARENT_DIR__ / "deploy_agent_windows_builder.ps1"

base_environment_used_files = [
    _AGENT_BUILD_DIR / "requirements.txt",
    _AGENT_BUILD_DIR / "monitors_requirements.txt",
    __SOURCE_ROOT__ / "dev-requirements.txt",
    __SOURCE_ROOT__ / "benchmarks/micro/requirements-compression-algorithms.txt",
]

PYTHON_ENVIRONMENT_DEPLOYER = EnvironmentDeployer(
    name="python",
    deployment_script_path=__PARENT_DIR__ / "install_python_and_ruby.sh"
)

BASE_ENVIRONMENT_DEPLOYER = EnvironmentDeployer(
    name="base_environment",
    deployment_script_path=base_environment_script_path,
    used_files=base_environment_used_files,
    base_deployer=PYTHON_ENVIRONMENT_DEPLOYER,
)


# class TestEnvironmentDeployer(BaseEnvironmentDeployer):
#     NAME = "test"
#     DEPLOYMENT_SCRIPT = __PARENT_DIR__ / "deploy_base_environment.sh"
#
#
# class AgentBuilderMachineDeployer(BaseEnvironmentDeployer):
#     NAME = "agent_builder"
#     if platform.system() != "Windows":
#         DEPLOYMENT_SCRIPT = __PARENT_DIR__ / "deploy_agent_linux_builder.sh"
#     else:
#         DEPLOYMENT_SCRIPT = __PARENT_DIR__ / "deploy_agent_windows_builder.ps1"
#

# class DockerizedAgentBuilderMachineDeployer(AgentBuilderMachineDeployer):
#     NAME = "dockerized_agent_builder"
#     BASE_DOCKER_IMAGE = "centos:7"


# Map deployers to their names.
DEPLOYERS: Dict[str, EnvironmentDeployer] = {
    dep.name: dep for dep in [
        PYTHON_ENVIRONMENT_DEPLOYER,
        BASE_ENVIRONMENT_DEPLOYER
    ]
}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    deploy_parser = subparsers.add_parser("deploy")
    get_info_parser = subparsers.add_parser("get-info")

    for p in [deploy_parser, get_info_parser]:
        p.add_argument("deployer_name", choices=DEPLOYERS.keys())

    get_info_parser.add_argument("info", choices=["checksum"])

    deploy_parser.add_argument("--base-docker-image", dest="base_docker_image")

    deploy_parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        help="Path to the directory which will be considered by the script is a cache. "
        "All 'cachable' intermediate results will be stored in it.",
    )

    args = parser.parse_args()

    # Find the deployer.
    deployer = DEPLOYERS[args.deployer_name]

    if args.command == "get-info":
        if args.info == "checksum":
            checksum = deployer.get_used_files_checksum()
            print(checksum)
        if args.info == "base-deployer":
            if deployer.base_deployer:
                print(deployer.base_deployer.name)

        exit(0)

    if args.command == "deploy":
        if args.base_docker_image:
            deployer.deploy_in_docker(
                base_docker_image=args.base_docker_image,
                cache_dir=args.cache_dir
            )
        else:
            deployer.deploy(
                cache_dir=args.cache_dir
            )


        exit(0)



