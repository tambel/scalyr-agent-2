import argparse
import json
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import package_builders
from agent_tools import constants
from tests.package_tests import current_test_specifications


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("build_name", choices=package_builders.PackageBuilder.ALL_BUILDERS.keys())
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_spec_name_parser = subparsers.add_parser("deployment-name")

    get_package_test_specs_parser = subparsers.add_parser("package-test-specs-matrix")

    package_filename_glob_parser = subparsers.add_parser("package-filename-glob")


    args = parser.parse_args()

    if args.command == "deployment-name":
        package_builder = package_builders.PackageBuilder.ALL_BUILDERS[args.build_name]
        print(package_builder.deployment.name)
        exit(0)

    if args.command == "package-filename-glob":
        package_builder = package_builders.PackageBuilder.ALL_BUILDERS[args.build_name]
        print(package_builder.filename_glob)
        exit(0)

    if args.command == "package-test-specs-matrix":
        package_builder = package_builders.PackageBuilder.ALL_BUILDERS[args.build_name]
        package_tests = current_test_specifications.PackageTest.PACKAGE_TESTS[args.build_name]
        test_specs_names = [s.unique_name for s in package_tests]
        test_specs_deployment_names = [s.deployment.name for s in package_tests]
        package_filename_globs = [package_builder.filename_glob for s in package_tests]

        matrix = {
            "include": []
        }

        for package_test in package_tests:
            runner_os = "ubuntu-20.04"
            if package_test.package_builder.PACKAGE_TYPE == constants.PackageType.MSI:
                if isinstance(package_test, current_test_specifications.Ec2BasedPackageTest):
                    runner_os = "windows-2019"

            test_json = {
                "test-name": package_test.unique_name,
                "package-filename-glob": package_builder.filename_glob,
                "deployment-name": package_test.deployment.name,
                "os": runner_os
            }
            matrix["include"].append(test_json)

        print(matrix)
        exit(0)
