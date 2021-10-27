import argparse
import pathlib as pl
import platform
import shlex
import shutil
import subprocess
import hashlib
from typing import Union

__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent.parent


class EnvironmentDeployer:
    DEPLOYMENT_SCRIPT: pl.Path = None
    FILES_USED_IN_DEPLOYMENT = []


    @classmethod
    def deploy(
        cls,
        cache_dir: Union[str, pl.Path] = None,
        in_docker_base_image: str = None
    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """
        # Prepare the build environment on the current system.

        # Choose the shell according to the operation system.
        if in_docker_base_image:
            cls._deploy_in_docker(
                cache_dir=cache_dir,
                base_image_name=in_docker_base_image
            )
            return

        if cls.DEPLOYMENT_SCRIPT.suffix == "ps1":
            shell = "powershell"
        else:
            shell = "bash"

        print(shutil.which("bash"))

        command = ['C:\\Program Files\\Git\\bin\\bash.exe', str(cls.DEPLOYMENT_SCRIPT)]
        #command = [str(cls.DEPLOYMENT_SCRIPT)]

        # If cache directory is presented, then we pass it as an additional argument to the
        # 'prepare build environment' script, so it can use the cache too.
        if cache_dir:
            command.append(str(pl.Path(cache_dir)))

        print("RUN")
        # Run the 'prepare build environment' script in previously chosen shell.

        #command = " ".join(command)
        print(command)
        subprocess.check_call(
            command,
            #shell=True
        )
        # subprocess.check_call(
        #     command,
        # )

    @classmethod
    def _deploy_in_docker(
        cls,
        base_image_name: str,
        cache_dir: Union[str, pl.Path] = None,

    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """
        # Instead of preparing the build environment on the current system, create the docker image and prepare the
        # build environment there. If cache directory is specified, then the docker image will be serialized to the
        # file and that file will be stored in the cache.

        # Get the name of the builder image.
        image_name = f"scalyr-build-environment-base-{cls.get_used_files_checksum()}".lower()

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
            pl.Path(cls.DEPLOYMENT_SCRIPT).relative_to(
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
                base_image_name,
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



    @classmethod
    def _get_files_used_in_build_environment(cls):
        """
        Get the list of all files which are used in the 'prepare-build-environment action.

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

        # The build environment preparation script is also has to be included.
        used_files.append(cls.DEPLOYMENT_SCRIPT)

        # Since the 'FILES_USED_IN_BUILD_ENVIRONMENT' class attribute can also contain directories, look for them and
        # include all files inside them recursively.
        for path in cls.FILES_USED_IN_DEPLOYMENT:
            path = pl.Path(path)
            if path.is_dir():
                used_files.extend(get_dir_files(path))
            else:
                used_files.append(path)

        return used_files

    @classmethod
    def get_used_files_checksum(cls):
        """
        Calculate the sha256 checksum of all files which are used in the "prepare-build-environment" action.
        """
        used_files = cls._get_files_used_in_build_environment()

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_path in used_files:
            file_path = pl.Path(file_path)
            sha256.update(str(file_path).encode())
            sha256.update(str(file_path.stat().st_mode).encode())
            sha256.update(file_path.read_bytes())

        checksum = sha256.hexdigest()
        return checksum


_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"


class TestEnvironmentDeployer(EnvironmentDeployer):
    DEPLOYMENT_SCRIPT = __PARENT_DIR__ / "deploy_test_environment.sh"
    FILES_USED_IN_DEPLOYMENT = [
        _AGENT_BUILD_DIR / "requirements.txt",
        _AGENT_BUILD_DIR / "monitors_requirements.txt",
        _AGENT_BUILD_DIR / "frozen-binary-builder-requirements.txt",
        __SOURCE_ROOT__ / "dev-requirements.txt",
        __SOURCE_ROOT__ / "benchmarks/micro/requirements-compression-algorithms.txt",
    ]


DEPLOYERS_TO_NAMES = {
    "test": TestEnvironmentDeployer
}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("deployer_name", choices=DEPLOYERS_TO_NAMES.keys())
    subparsers = parser.add_subparsers(dest="command")

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        help="Path to the directory which will be considered by the script is a cache. "
        "All 'cachable' intermediate results will be stored in it.",
    )

    deploy_parser.add_argument(
        "--in-docker-base-image",
        dest="in_docker_base_image",
        type=str
    )

    dump_checksum_parser = subparsers.add_parser("dump-checksum")
    dump_checksum_parser.add_argument(
        "checksum_file_path",
        help="The path of the output file with the checksum in it.",
    )

    args = parser.parse_args()

    # Find the deployer class.
    deployer_cls = DEPLOYERS_TO_NAMES[args.deployer_name]

    if args.command == "dump-checksum":
        checksum = deployer_cls.get_used_files_checksum()

        checksum_output_path = pl.Path(args.checksum_file_path)
        checksum_output_path.parent.mkdir(exist_ok=True, parents=True)
        checksum_output_path.write_text(checksum)

        exit(0)

    if args.command == "deploy":
        print("deploy!")
        deployer_cls.deploy(
            cache_dir=args.cache_dir,
            in_docker_base_image=args.in_docker_base_image
        )
        exit(0)



