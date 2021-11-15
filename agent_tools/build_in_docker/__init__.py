import subprocess
import shlex
import pathlib as pl
import os

from agent_tools import constants
from agent_common import utils as common_utils

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent.parent


def build_stage(
        command: str,
        stage_name: str,
        architecture: constants.Architecture,
        image_name: str,
        base_image_name: str,
        output_path: pl.Path,
):

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"

    subprocess.check_call(
        [
            "docker",
            "build",
            "--platform",
            architecture.as_docker_platform.value,
            "-t",
            image_name,
            "--build-arg",
            f"BASE_IMAGE_NAME={base_image_name}",
            "--build-arg",
            f"BUILD_COMMAND={command}",
            "--build-arg",
            f"BUILD_STAGE={stage_name}",
            "-f",
            str(__PARENT_DIR__ / "Dockerfile"),
            str(__SOURCE_ROOT__),
        ],
        env=env
    )

    # The image is build and package has to be fetched from it, so create the container...

    # Remove the container with the same name if exists.
    container_name = image_name

    subprocess.check_call(["docker", "rm", "-f", container_name])

    # Create the container.
    subprocess.check_call(
        ["docker", "create", "--name", container_name, image_name]
    )

    subprocess.check_call(
        [
            "docker",
            "cp",
            "-a",
            # f"{container_name}:/tmp/build/.",
            # str(output_path),
            f"{container_name}:/tmp/build/.",
            str(output_path)
        ],
    )
