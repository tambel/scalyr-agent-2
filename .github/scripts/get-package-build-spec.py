import argparse
import json
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import build_and_test_specs
from agent_tools import constants


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_spec_name_parser = subparsers.add_parser("deployment-name")
    build_spec_name_parser.add_argument("build_spec_name", choices=build_and_test_specs.PACKAGE_BUILD_SPECS.keys())

    get_test_deployments_parser = subparsers.add_parser("test-deployment-names")
    get_test_deployments_parser.add_argument("build_spec_name", choices=build_and_test_specs.PACKAGE_BUILD_SPECS.keys())

    get_package_test_specs_parser = subparsers.add_parser("package-test-specs-matrix")
    get_package_test_specs_parser.add_argument("build_spec_name", choices=build_and_test_specs.PACKAGE_BUILD_SPECS.keys())

    package_filename_glob_parser = subparsers.add_parser("package-filename-glob")
    package_filename_glob_parser.add_argument("build_spec_name", choices=build_and_test_specs.PACKAGE_BUILD_SPECS.keys())


    args = parser.parse_args()

    if args.command == "deployment-name":
        build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[args.build_spec_name]
        print(build_spec.deployment.name)
        exit(0)

    if args.command == "package-filename-glob":
        build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[args.build_spec_name]
        print(build_spec.filename_glob)
        exit(0)

    if args.command == "package-test-specs-matrix":
        build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[args.build_spec_name]
        test_specs = build_and_test_specs.PACKAGE_BUILD_TO_TEST_SPECS[args.build_spec_name]
        test_specs_names = [s.name for s in test_specs]
        matrix = {"test-name": test_specs_names}
        print(matrix)

    if args.command == "test-deployment-names":
        build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[args.build_spec_name]
        test_specs = build_and_test_specs.PACKAGE_BUILD_TO_TEST_SPECS[args.build_spec_name]

        test_specs_names = [s.deployment.name for s in test_specs]
        print(test_specs_names)

        exit(0)
