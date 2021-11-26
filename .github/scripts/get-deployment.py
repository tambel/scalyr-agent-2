import argparse
import json
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages.
sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import constants
from agent_tools import environment_deployments

# Import those files, since they are create all needed builders and tests.
# Without them there also won't be any deployments.
from tests.package_tests import current_test_specifications
from agent_tools import package_builders


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--cache-dir", dest="cache_dir")

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

        deployment = environment_deployments.Deployment.ALL_DEPLOYMENTS[args.name]

        step_checksums = []
        for step in deployment.steps:
            step_checksums.append(step.cache_key)

        print(json.dumps(list(reversed(step_checksums))))

        exit(0)

