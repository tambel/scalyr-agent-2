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
import dataclasses
import json
import pathlib as pl
import shlex
import tarfile
import abc
import argparse
import platform
import shutil
import subprocess
import time
import sys
import stat
import hashlib
import uuid
import os
import re
import io
import logging

from typing import Union, Optional, Type

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__

sys.path.append(str(__SOURCE_ROOT__))

from agent_build import package_builders

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"


if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    build_spec_parser = subparsers.add_parser("get-build-spec")
    build_parser = subparsers.add_parser("build")

    for p in [build_parser, build_spec_parser]:
        p.add_argument(
            "package_spec_name",
            type=str,
            choices=list(package_builders.SPECS.keys()),
            help="Type of the package to build.",
        )

    build_spec_parser.add_argument(
        "spec",
        choices=[
            "deployers",
            "package-filename-glob",
            "base-docker-image"
        ]
    )

    build_parser.add_argument("--build-tests", action="store_true")

    build_parser.add_argument(
        "--locally",
        action="store_true",
        help="Perform the build on the current system which runs the script. Without that, some packages may be built "
        "by default inside the docker.",
    )

    build_parser.add_argument(
        "--output-dir",
        required=True,
        type=str,
        dest="output_dir",
        help="The directory where the result package has to be stored.",
    )

    build_parser.add_argument(
        "--no-versioned-file-name",
        action="store_true",
        dest="no_versioned_file_name",
        default=False,
        help="If true, will not embed the version number in the artifact's file name.  This only "
        "applies to the `tarball` and container builders artifacts.",
    )

    build_parser.add_argument(
        "-v",
        "--variant",
        dest="variant",
        default=None,
        help="An optional string that is included in the package name to identify a variant "
        "of the main release created by a different packager.  "
        "Most users do not need to use this option.",
    )

    args = parser.parse_args()

    # Find the builder class.
    package_builder_spec = package_builders.SPECS[args.package_spec_name]

    if args.command == "get-build-spec":
        if args.spec == "deployers":
            deployers = package_builder_spec.used_deployers
            if deployers:
                deployer_names = [d.name for d in deployers]
                print(",".join(deployer_names))

        if args.spec == "package-filename-glob":
            print(package_builder_spec.filename_glob)

        if args.spec == "base-docker-image":
            if package_builder_spec.base_image.image_name:
                print(package_builder_spec.base_image)

        if args.spec == "architecture":
            if package_builder_spec.architecture:
                print(package_builder_spec.architecture.value)

        exit(0)

    if args.command == "build":
        logging.info(f"Build package '{args.package_spec_name}'...")
        output_path = pl.Path(args.output_dir)

        # Build only frozen binary tests instead of package.
        if args.build_tests:
            package_builders.build_test_runner_frozen_binary(
                package_build_spec=package_builder_spec,
                output_path=output_path,
                locally=args.locally
            )
            exit(0)

        package_builders.build_package(
            package_build_spec=package_builder_spec,
            output_path=output_path,
            locally=args.locally,
            variant=args.variant,
            no_versioned_file_name=args.no_versioned_file_name
        )
