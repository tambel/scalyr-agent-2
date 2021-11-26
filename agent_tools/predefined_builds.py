import argparse
import logging
import pathlib as pl
import sys
import json


__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import environment_deployments
from agent_tools import constants


_SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployment_steps"


# ################################### Deployments ######################################


# Docker based step that build image with Python and other needed tools.
# The specific of this Python, is that it is build against very early version of glibc (2.12), so the statically bundled
# frozen binary has to work starting from centos:6
class InstallPythonStep(environment_deployments.DockerFileDeploymentStep):
    USED_FILES = [_SCRIPTS_DIR_PATH / "build-python" / "*"]
    DOCKERFILE_PATH = _SCRIPTS_DIR_PATH / "build-python" / "Dockerfile"


# Paths to the helper files that may be helpful for the main deployment script.
_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS = [
    # bash library that provides a simple caching logic.
    __SOURCE_ROOT__ / _SCRIPTS_DIR_PATH / "cache_lib.sh"
]

_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"

# Glob that has to match all requirement files that are needed for the agent build.
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_DIR / "requirement-files" / "*.txt"


# Step that rn small script which install all needed agent build requirements from requirement files.
class InstallBuildRequirementsStep(environment_deployments.ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_build_environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


# Step that rn small script which installs requirements from the test/dev environment.
class InstallTestRequirementsDeploymentStep(environment_deployments.ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy-dev-environment.sh"
    USED_FILES = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH, __SOURCE_ROOT__ / "dev-requirements.txt"
    ]


# Step that prepare all tools that are needed for the windows package build.
# For now it just a WIX toolset, which is needed to  create msi packages.
class InstallWindowsBuilderToolsStep(environment_deployments.ShellScriptDeploymentStep):
    SCRIPT_PATH = _SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1"
    USED_FILES = used_files = [
        *_HELPER_DEPLOYMENT_SCRIPTS_AND_LIBS,
        _AGENT_REQUIREMENT_FILES_PATH
    ]


# Common test environment. Just installs all dev environment to the current system.
# Used by Github Actions CI/CD.
COMMON_TEST_DEPLOYMENT = environment_deployments.Deployment(
    name="test_environment",
    architecture=constants.Architecture.X86_64,
    step_classes=[InstallBuildRequirementsStep]
)



if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Name of the deployment.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument(
        "--cache-dir", dest="cache_dir", help="Cache directory to save/reuse deployment results."
    )

    get_all_deployments_parser = subparsers.add_parser("get-deployment-all-cache-names")

    subparsers.add_parser("list")

    args = parser.parse_args()

    if args.command == "deploy":
        # Perform the deployment with specified name.
        deployment = environment_deployments.Deployment.ALL_DEPLOYMENTS[args.name]

        cache_dir = None

        if args.cache_dir:
            cache_dir = pl.Path(args.cache_dir)

        deployment.deploy(
            cache_dir=cache_dir,
        )

    if args.command == "get-deployment-all-cache-names":
        # A special command which is needed to perform the Github action located in
        # '.github/actions/perform-deployment'. The command provides names of the caches of the deployment step, so the
        # Github action knows what keys to use to cache the results of those steps.

        deployment = environment_deployments.Deployment.ALL_DEPLOYMENTS[args.name]

        # Get cache names of from all steps and print them as JSON list. This format is required by the mentioned
        # Github action.
        step_checksums = []
        for step in deployment.steps:
            step_checksums.append(step.cache_key)

        print(json.dumps(list(reversed(step_checksums))))

        exit(0)
