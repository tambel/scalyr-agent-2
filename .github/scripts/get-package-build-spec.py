import argparse
import sys
import pathlib as pl
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import build_and_test_specs
from agent_tools import constants


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("build_spec_name", choices=build_and_test_specs.PACKAGE_BUILD_SPECS.keys())
    args = parser.parse_args()

    build_spec = build_and_test_specs.PACKAGE_BUILD_SPECS[args.build_spec_name]

    print(build_spec.deployment.name)
    parser.add_argument("deployment")