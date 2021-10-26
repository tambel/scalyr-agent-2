import pathlib as pl
from typing import Union


class EnvironmentDeployer:
    DEPLOYMENT_SCRIPT = None

    @classmethod
    def deploy(
        cls, cache_dir: Union[str, pl.Path] = None, locally: bool = False
    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """
        if locally or not cls.DOCKERIZED:
            # Prepare the build environment on the current system.

            # Choose the shell according to the operation system.
            if platform.system() == "Windows":
                shell = "powershell"
            else:
                shell = "bash"

            command = [shell, str(cls.PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH)]

            # If cache directory is presented, then we pass it as an additional argument to the
            # 'prepare build environment' script, so it can use the cache too.
            if cache_dir:
                command.append(str(pl.Path(cache_dir)))

            # Run the 'prepare build environment' script in previously chosen shell.
            subprocess.check_call(
                command,
            )
        else:
            # Instead of preparing the build environment on the current system, create the docker image and prepare the
            # build environment there. If cache directory is specified, then the docker image will be serialized to the
            # file and that file will be stored in the cache.

            # Get the name of the builder image.
            image_name = cls._get_build_environment_docker_image_name()

            # Before the build, check if there is already an image with the same name. The name contains the checksum
            # of all files which are used in it, so the name identity also guarantees the content identity.
            output = (
                subprocess.check_output(["docker", "images", "-q", image_name])
                .decode()
                .strip()
            )

            if output:
                # The image already exists, skip the build.
                print(
                    f"Image '{image_name}' already exists, skip the build and reuse it."
                )
                return

            save_to_cache = False

            # If cache directory is specified, then check if the image file is already there and we can reuse it.
            if cache_dir:
                cache_dir = pl.Path(cache_dir)
                cached_image_path = cache_dir / image_name
                if cached_image_path.is_file():
                    print(
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

            print(f"Build image '{image_name}'")

            # Create the builder image.
            # Instead of using the 'docker build', just create the image from 'docker commit' from the container.

            container_root_path = pl.Path("/scalyr-agent-2")

            # All files, which are used in the build have to be mapped to the docker container.
            volumes_mappings = []
            for used_path in cls._get_files_used_in_build_environment():
                rel_used_path = pl.Path(used_path).relative_to(__SOURCE_ROOT__)
                abs_host_path = __SOURCE_ROOT__ / rel_used_path
                abs_container_path = container_root_path / rel_used_path
                volumes_mappings.extend(["-v", f"{abs_host_path}:{abs_container_path}"])

            # Map the 'prepare environment' script's path to the docker.
            container_prepare_env_script_path = pl.Path(
                container_root_path,
                pl.Path(cls.PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH).relative_to(
                    __SOURCE_ROOT__
                ),
            )

            container_name = cls.__name__

            # Remove if such container exists.
            subprocess.check_call(["docker", "rm", "-f", container_name])

            # Create container and run the 'prepare environment' script in it.
            subprocess.check_call(
                [
                    "docker",
                    "run",
                    "-i",
                    "--name",
                    container_name,
                    *volumes_mappings,
                    cls.BASE_DOCKER_IMAGE,
                    str(container_prepare_env_script_path),
                ]
            )

            # Save the current state of the container into image.
            subprocess.check_call(["docker", "commit", container_name, image_name])

            # Save image if caching is enabled.
            if cache_dir and save_to_cache:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached_image_path = cache_dir / image_name
                print(f"Saving '{image_name}' image file into cache.")
                with cached_image_path.open("wb") as f:
                    subprocess.check_call(["docker", "save", image_name], stdout=f)