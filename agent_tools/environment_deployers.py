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
import enum
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

from agent_tools import constants


class EnvironmentDeployer:
    """
    This abstraction responsible for deployment of the some environment in the target machine.
    Basically, it is just a wrapper around some shell script and a set of files which are used by this shell.

    The state of the desired environment should be defined in the shell script.

    Knowing what files are used, the deployer can calculate their checksum, and this can be uses as a cache key for
        some CI/CD platform, providing "CI/CD platform agnostic" and unified way of preparing/deploying needed
        environments.

    Deployer can also run its script inside docker.

    Deployers are used in this project to prepare build and test environments for the agent. Using their ability to
        operate inside the docker, they help to achieve a unified way of building and testing agent packages, locally
        and on CI/CD.
    """

    def __init__(
            self,
            name: str,
            deployment_script_path: Union[str, pl.Path],
            used_files: list = None,
    ):
        """
        :param name: Name of the deployment.
        :param deployment_script_path: Path to the script which is executed during the deployment.
        :param used_files: List files used in the deployment. Can be globs.
        """
        self._name = name
        self._deployment_script_path = deployment_script_path
        self._used_files = used_files or []

    @property
    def name(self):
        return self._name

    def run(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Perform the deployment by running the shell script. It also allows perform it inside the docker.

        :param cache_dir: Path to the directory which will be used as cache. It is passed to the shell script as a first
            argument, so it it possible to save/reuse some intermediate result in the script. It may be useful if
            deployment has to be done on some CI/CD machine, which is new on each run. When deployer operates in docker,
            then it caches the whole result image by using 'docker save'. On the second run, the deployer can load the
            image from this cached file without rebuilding.
        """

        # Choose the shell according to the operation system.
        if self._deployment_script_path.suffix == ".ps1":
            shell = "powershell"
        else:
            shell = shutil.which("bash")

        command = [shell, str(self._deployment_script_path)]

        # If cache directory is presented, then we pass it as an additional argument to the
        # script, so it can use the cache too.
        if cache_dir:
            command.append(str(pl.Path(cache_dir)))

        # Run the script in previously chosen shell.
        subprocess.check_call(
            command,
        )

    def run_in_docker(
        self,
        base_docker_image: str,
        result_image_name: str,
        architecture: constants.Architecture,
        cache_dir: Union[str, pl.Path] = None,

    ):
        """
        This function does the same deployment but inside the docker.
        :param base_docker_image: Name of the base docker image. The shell script will be executed inside its container.
        :param result_image_name: The name of the result image.
        :param architecture: Type of the processor architecture. Docker can use emulation to support different platforms.
        :param cache_dir: The cache directory. the same as in the main functions.
        """

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
                    f"Cached image {result_image_name} file with the deployer '{self._name}' has been found, loading and reusing it instead of building."
                )
                subprocess.check_call(
                    ["docker", "load", "-i", str(cached_image_path)]
                )
                return
            else:
                # Cache is used but there is no suitable image file. Set the flag to signal that the built
                # image has to be saved to the cache.
                save_to_cache = True

        logging.info(f"Build image '{result_image_name}' from base image '{base_docker_image}' with the deployer '{self._name}'.")

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
            pl.Path(self._deployment_script_path).relative_to(
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
                architecture.as_docker_platform.value,
                "-i",
                "--name",
                container_name,
                *volumes_mappings,
                base_docker_image,
                str(container_prepare_env_script_path),
            ]
        )

        # Save the current state of the container into image.
        subprocess.check_call(["docker", "commit", container_name, result_image_name])

        # Save image if caching is enabled.
        if cache_dir and save_to_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_image_path = cache_dir / result_image_name
            logging.info(f"Saving '{result_image_name}' image file into cache.")
            with cached_image_path.open("wb") as f:
                subprocess.check_call(["docker", "save", result_image_name], stdout=f)

    def _get_used_files(self) -> List[pl.Path]:
        """
            Get the list of all files which are used in the deployment.
            This is basically needed to calculate their checksum.
        """

        # The shell script is also has to be included.
        used_files = [self._deployment_script_path]

        # Since the list of used files can also contain directories, look for them and
        # include all files inside them recursively.
        for path in self._used_files:
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