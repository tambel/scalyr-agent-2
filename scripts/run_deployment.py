import collections
import itertools
import sys
import pathlib as pl
import logging
import argparse
from typing import Dict, List
import json

_SOURCE_ROOT = pl.Path(__file__).parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

from agent_tools.environment_deployments import deployments
from agent_build import package_builders
from tests.package_tests import current_test_specifications


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    get_list_parser = subparsers.add_parser("list")
    deployment_subparser = subparsers.add_parser("deployment")
    deployment_subparser.add_argument("deployment_name", choices=deployments.ALL_DEPLOYMENTS.keys())

    deployment_subparsers = deployment_subparser.add_subparsers(dest="deployment_command", required=True)
    deploy_parser = deployment_subparsers.add_parser("deploy")
    deploy_parser.add_argument(
        "--cache-dir", dest="cache_dir", help="Cache directory to save/reuse deployment results."
    )

    get_all_deployments_parser = deployment_subparsers.add_parser("get-deployment-all-cache-names")

    args = parser.parse_args()

    if args.command == "deploy":
        # Perform the deployment with specified name.
        deployment = deployments.ALL_DEPLOYMENTS[args.deployment_name]

        cache_dir = None

        if args.cache_dir:
            cache_dir = pl.Path(args.cache_dir)

        deployment.deploy(
            cache_dir=cache_dir,
        )
        exit(0)

    if args.command == "deployment":
        if args.deployment_command == "get-deployment-all-cache-names":
            # A special command which is needed to perform the Github action located in
            # '.github/actions/perform-deployment'. The command provides names of the caches of the deployment step,
            # so the Github action knows what keys to use to cache the results of those steps.

            deployment = deployments.ALL_DEPLOYMENTS[args.deployment_name]

            # Get cache names of from all steps and print them as JSON list. This format is required by the mentioned
            # Github action.
            step_checksums = []
            for step in deployment.steps:
                step_checksums.append(step.cache_key)

            print(json.dumps(list(reversed(step_checksums))))

            exit(0)

        if args.command == "list":
            for deployment_name in sorted(deployments.ALL_DEPLOYMENTS.keys()):
                print(deployment_name)
            exit(0)