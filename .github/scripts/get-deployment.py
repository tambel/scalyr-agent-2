import argparse
import json
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import build_and_test_specs
from agent_tools import constants


def run_deployer(
        deployer_name: str,
        base_docker_image: str = None,
        architecture_string: str = None,
        cache_dir: str = None
):

    deployer = build_and_test_specs.DEPLOYERS[deployer_name]

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

    checksum_parser = subparsers.add_parser("checksum")
    checksum_parser.add_argument("name")

    previous_deployer_parser = subparsers.add_parser("previous-deployment")
    previous_deployer_parser.add_argument("name")

    deployments_string_array = subparsers.add_parser("deployments-as-string-array")
    deployments_string_array.add_argument("name")

    first_deployer_name_parser = subparsers.add_parser("get-first-deployment-name-from-array-list")
    first_deployer_name_parser.add_argument("list")

    other_deployer_names_parser = subparsers.add_parser("get-other-deployment-names-from-array-list")
    other_deployer_names_parser.add_argument("list")

    get_all_deployments_parser = subparsers.add_parser("get-deployment-all-cache-names")
    get_all_deployments_parser.add_argument("deployment_name")

    subparsers.add_parser("list")



    #parser.add_argument("deployer_command", choices=["deploy", "checksum", "result-image-name", "list"])
    # parser.add_argument("deployer_name", choices=build_and_test_specs.DEPLOYERS.keys())
    # parser.add_argument("--base-docker-image", dest="base_docker_image")

    # parser.add_argument("--architecture")

    args = parser.parse_args()

    if args.command == "list":
        for name in build_and_test_specs.DEPLOYMENTS.keys():
            print(name)
        exit(0)

    if args.command == "checksum":
        deployment = build_and_test_specs.DEPLOYMENTS[args.name]
        checksum = deployment.checksum
        print(checksum)
        exit(0)

    if args.command == "previous-deployment":
        deployment = build_and_test_specs.DEPLOYMENTS[args.name]
        if isinstance(deployment, build_and_test_specs.FollowingDeployment):
            print(deployment.previous_deployment.name)

        exit(0)

    if args.command == "deploy":
        deployment = build_and_test_specs.DEPLOYMENTS[args.name]
        deployment.deploy(
            cache_dir=args.cache_dir,
        )

    if args.command == "deployments-as-string-array":
        deployment = build_and_test_specs.DEPLOYMENTS[args.name]

        curr = deployment

        names = []
        while True:
            names.append(curr.name)
            if isinstance(curr, build_and_test_specs.InitialDeployment):
                break
            curr = curr.previous_deployment

        print(",".join(reversed(names)))

        exit(0)

    if args.command == "get-first-deployment-name-from-array-list":
        names = args.list.split(",")
        if names:
            print(names[0])

    if args.command == "get-deployment-all-cache-names":
        deployment = build_and_test_specs.DEPLOYMENTS[args.deployment_name]

        curr = deployment

        names = []
        while True:
            names.append(curr.cache_name)
            if isinstance(curr, build_and_test_specs.InitialDeployment):
                break
            curr = curr.previous_deployment

        print(json.dumps(list(reversed(names))))

        exit(0)

