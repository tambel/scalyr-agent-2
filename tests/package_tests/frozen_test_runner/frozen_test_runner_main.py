# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This script is an entry point for the frozen package test runner. See more in the 'build_test_runner_frozen_binary.py'
file in the same directory.
"""

import argparse
import pathlib as pl
import sys
import logging

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages.
sys.path.append(str(__SOURCE_ROOT__))


from tests.package_tests import current_test_specifications


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("test_spec_name")
    parser.add_argument("--package-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    package_test_spec = current_test_specifications.PackageTest.ALL_TESTS[args.test_spec_name]

    package_test_spec.run_test_locally(
        package_path=pl.Path(args.package_path),
        scalyr_api_key=args.scalyr_api_key
    )