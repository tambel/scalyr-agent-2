import argparse
import json
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import package_builders
from agent_tools import constants
from agent_tools import environment_deployments
from tests.package_tests import current_test_specifications


def run_deployer(
        deployer_name: str,
        base_docker_image: str = None,
        architecture_string: str = None,
        cache_dir: str = None
):

    deployer = environment_deployments.Deployment.ALL_DEPLOYMENTS[deployer_name]

    if args.base_docker_image:
        if not architecture_string:
            raise ValueError("Can not run deployer in docker without architecture.")
        deployer.run_in_docker(
            base_docker_image=base_docker_image,
            architecture=constants.Architecture(architecture_string),
            cache_dir=cache_dir,
        )
    else:
        deployer.run(
            cache_dir=args.cache_dir
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("name")
    deploy_parser.add_argument("--cache-dir", dest="cache_dir")

    get_all_deployments_parser = subparsers.add_parser("get-deployment-all-cache-names")
    get_all_deployments_parser.add_argument("deployment_name")

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

        deployment = environment_deployments.Deployment.ALL_DEPLOYMENTS[args.deployment_name]

        step_checksums = []
        for step in deployment.steps:
            step_checksums.append(step.cache_key)

        print(json.dumps(list(reversed(step_checksums))))

        exit(0)

