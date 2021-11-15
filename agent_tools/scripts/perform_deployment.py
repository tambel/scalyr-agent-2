import argparse
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import environment_deployments


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")
    parser = argparse.ArgumentParser()

    all_deployment_specs = environment_deployments.DeploymentSpec.ALL_DEPLOYMENT_SPECS

    parser.add_argument(
        "deployment_name",
        choices=all_deployment_specs.keys()
    )
    parser.add_argument("--cache-dir", dest="cache_dir", required=False)

    args = parser.parse_args()

    deployment_spec = all_deployment_specs[args.deployment_name]

    deployment_spec.deploy(
        cache_dir=args.cache_dir
    )
