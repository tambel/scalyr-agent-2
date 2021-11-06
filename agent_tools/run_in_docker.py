import argparse
import base64
import importlib
import importlib.util
import json
import shlex
import subprocess
import os
import pathlib as pl
import sys
import inspect
import pickle
from typing import Callable, List, Dict, Union

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent



sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import constants
from agent_tools import environment_deployers as deployers


def dockerized_function(
        func: Callable,
        image_name: str,
        base_image: str,
        architecture: constants.Architecture,
        build_stage: str,
        used_deployers: List[deployers.EnvironmentDeployer] = None,
        path_mappings: Dict[Union[str, pl.Path], Union[str, pl.Path]] = None
):
    path_mappings = path_mappings or dict()
    final_path_mappings: Dict[pl.Path, pl.Path] = {}

    for host_path, container_path in path_mappings.items():
        final_path_mappings[pl.Path(host_path)] = pl.Path(container_path)

    used_deployers = used_deployers or []
    current_base_image = base_image
    for deployer in used_deployers:

        deployer.deploy_in_docker(
            base_docker_image=current_base_image,
            architecture=architecture
        )
        current_base_image = deployer.get_image_name(architecture=architecture)


    func_module = inspect.getmodule(func)

    if func_module.__name__ == "__main__":
        module_path = pl.Path(func_module.__file__).relative_to(__SOURCE_ROOT__)

        module_path = module_path.parent / module_path.stem
        func_module_name = ".".join(str(module_path).split(os.path.sep))
        func_module = importlib.import_module(func_module_name)
        module_function = getattr(func_module, func.__name__)
    else:
        module_function = func

    pickled_function = pickle.dumps(module_function)
    pickled_function_base_64 = base64.b64encode(pickled_function).decode()

    command_args = [
        "python3",
        "/scalyr-agent-2/agent_tools/run_in_docker.py",
        #func_module_name,
        #func.__name__,
        pickled_function_base_64
    ]

    dockerfile_path = __PARENT_DIR__ / "Dockerfile"

    def call(*args, **kwargs):

        if hasattr(sys, "dockerized"):
            return func(*args, **kwargs)

        nonlocal final_path_mappings

        def handle_arg(arg):

            mapped_path = final_path_mappings.get(pl.Path(arg))
            if mapped_path:
                return str(mapped_path)
            return arg

        final_args = []
        for arg in args:
            final_args.append(handle_arg(arg))

        final_kwargs = {}
        for k,v in kwargs.items():
            final_kwargs[k] = handle_arg(v)

        args_json = {"args": final_args, "kwargs": final_kwargs}


        command_args.append(
            json.dumps(args_json)
        )

        command = shlex.join(command_args)

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
                f"BASE_IMAGE_NAME={current_base_image}",
                "--build-arg",
                f"BUILD_COMMAND={command}",
                "--build-arg",
                f"BUILD_STAGE={build_stage}",
                "-f",
                str(dockerfile_path),
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

        for host_path, container_path in final_path_mappings.items():
            # Copy package output from the container.

            if not host_path.exists():
                host_path.mkdir(parents=True)

            subprocess.check_call(
                [
                    "docker",
                    "cp",
                    "-a",
                    # f"{container_name}:/tmp/build/.",
                    # str(output_path),
                    f"{container_name}:{container_path}/.",
                    str(host_path)
                ],
            )

        # Remove the container.
        subprocess.check_call(["docker", "rm", "-f", container_name])

    return call


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # parser.add_argument("module_name")
    # parser.add_argument("function_name")
    parser.add_argument("pickled_function")
    parser.add_argument("args_json")

    args = parser.parse_args()

    # module_name = args.module_name
    #
    # module = importlib.import_module(module_name)
    #
    # module_function = getattr(module, args.function_name)

    pickled_func = base64.b64decode(args.pickled_function)
    func = pickle.loads(pickled_func)

    all_args = json.loads(args.args_json)


    function_args = all_args["args"]
    function_kwargs = all_args["kwargs"]

    setattr(sys, "dockerized", True)

    func(*function_args, **function_kwargs)