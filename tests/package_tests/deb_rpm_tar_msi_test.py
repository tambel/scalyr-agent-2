#!/usr/bin/env python3

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
import abc
import pathlib
import pathlib as pl
import shlex
import subprocess
import json
import time
import os
import tarfile
import logging
import sys
from typing import Union

from agent_tools import package_builders
from agent_tools import constants
from agent_tools import build_and_test_specs
import agent_common.utils
from tests.package_tests.common import LogVerifier, AgentLogRequestStatsLineCheck, AssertAgentLogLineIsNotAnErrorCheck


USER_HOME = pl.Path("~").expanduser()

# Flag that indicates that this test script is executed as frozen binary.
__frozen__ = hasattr(sys, "frozen")


class PackagedAgentRunner(abc.ABC):

    def __init__(
            self,
            package_path: Union[str, pl.Path],
            package_build_spec: build_and_test_specs.PackageBuildSpec
    ):
        self._package_path = pl.Path(package_path)
        self._package_build_spec = package_build_spec

    def install_package(self):
        pass

    def remove_package(self):
        pass

    def run_agent_command(self, command_args, *args, env=None,shell=True, **kwargs):
        env = env or os.environ.copy()
        paths = env['PATH']
        env["PATH"] = f"{self.agent_bin_path}{os.pathsep}{paths}"
        subprocess.check_call(
            f"scalyr-agent-2 {shlex.join(command_args)}",
            *args,
            env=env,
            shell=shell,
            **kwargs
        )

    @property
    @abc.abstractmethod
    def config_path(self) -> pl.Path:
        pass

    @property
    @abc.abstractmethod
    def agent_log_path(self) -> pl.Path:
        pass

    @property
    @abc.abstractmethod
    def agent_bin_path(self) -> pl.Path:
        pass

    def configure_agent(self, api_key: str, config: dict = None):

        config = config or {}
        config["api_key"] = api_key

        config["server_attributes"] = {"serverHost": "ARTHUR_TEST"}

        # TODO enable and test system and process monitors
        config["implicit_metric_monitor"] = False
        config["implicit_agent_process_metrics_monitor"] = False
        config["verify_server_certificate"] = False
        self.config_path.write_text(json.dumps(config))

    def start_agent(self):
        self.run_agent_command(["start"])

    def get_agent_status(self):
        self.run_agent_command(["status", "-v"])

    def stop_agent(self):
        self.run_agent_command(["stop"])


class LinuxFhsFilesystemBasedPackageRunner(PackagedAgentRunner):
    @property
    def config_path(self) -> pl.Path:
        return pl.Path("/etc/scalyr-agent-2/agent.json")

    @property
    def agent_log_path(self) -> pl.Path:
        return pl.Path("/var/log/scalyr-agent-2/agent.log")

    @property
    def agent_bin_path(self) -> pl.Path:
        return pl.Path("/usr/sbin/")


class DebAgentRunner(LinuxFhsFilesystemBasedPackageRunner):
    def install_package(self):
        env = os.environ.copy()
        if __frozen__:
            env[
                "LD_LIBRARY_PATH"
            ] = f'/lib/x86_64-linux-gnu:{os.environ["LD_LIBRARY_PATH"]}'

        subprocess.check_call(
            ["dpkg", "-i", str(self._package_path)],
            env=env
        )

    def remove_package(self):
        env = os.environ.copy()
        if __frozen__:
            env[
                "LD_LIBRARY_PATH"
            ] = f'/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:{os.environ["LD_LIBRARY_PATH"]}'
        subprocess.check_call(
            f"apt-get remove -y scalyr-agent-2", shell=True,
            env=env
        )


class RpmPAckageRunner(LinuxFhsFilesystemBasedPackageRunner):
    def install_package(self):
        env = os.environ.copy()

        if __frozen__:
            env["LD_LIBRARY_PATH"] = "/libx64"

        subprocess.check_call(
            ["rpm", "-i", str(self._package_path)],
            env=env
        )

    def remove_package(self):
        env = os.environ.copy()
        if __frozen__:
            env["LD_LIBRARY_PATH"] = "/libx64"

        subprocess.check_call(
            f"yum remove -y scalyr-agent-2", shell=True,
            env=env
        )


class CentralInstallPathPackageRunner(PackagedAgentRunner):
    @property
    @abc.abstractmethod
    def root_path(self) -> pl.Path:
        pass

    @property
    def config_path(self) -> pl.Path:
        return self.root_path / "config" / "agent.json"

    @property
    def agent_log_path(self) -> pl.Path:
        return self.root_path / "log" / "agent.log"

    @property
    def agent_bin_path(self) -> pl.Path:
        return self.root_path / "bin"


class TarballAgentRunner(CentralInstallPathPackageRunner):
    def install_package(self):
        tar = tarfile.open(self._package_path)
        tar.extractall(pl.Path("~").expanduser())
        tar.close()

    @property
    def root_path(self):
        install_path = pl.Path("~").expanduser() / "scalyr-agent"
        return install_path


class MsiAgentRunner(CentralInstallPathPackageRunner):
    def install_package(self):
        subprocess.check_call(f"msiexec.exe /I {self._package_path} /quiet", shell=True)

    @property
    def root_path(self) -> pl.Path:
        return pl.Path(os.environ["programfiles(x86)"]) / "Scalyr"


# def install_deb_package(package_path: pl.Path):
#     env = os.environ.copy()
#     if __frozen__:
#         env[
#             "LD_LIBRARY_PATH"
#         ] = f'/lib/x86_64-linux-gnu:{os.environ["LD_LIBRARY_PATH"]}'
#
#     subprocess.check_call(
#         ["dpkg", "-i", str(package_path)],
#         env=env
#     )
#
#
# def install_rpm_package(package_path: pl.Path):
#     env = os.environ.copy()
#
#     if __frozen__:
#         env["LD_LIBRARY_PATH"] = "/libx64"
#
#     subprocess.check_call(
#         ["rpm", "-i", str(package_path)],
#         env=env
#     )
#
#
# def install_tarball(package_path: pl.Path):
#     tar = tarfile.open(package_path)
#     tar.extractall(USER_HOME)
#     tar.close()
#
#
# def _get_tarball_install_path() -> pl.Path:
#     matched_paths = list(USER_HOME.glob("scalyr-agent-*.*.*"))
#     if len(matched_paths) == 1:
#         return pl.Path(matched_paths[0])
#
#     raise ValueError("Can't find extracted tar file.")
#
#
# def install_msi_package(package_path: pl.Path):
#     subprocess.check_call(f"msiexec.exe /I {package_path} /quiet", shell=True)
#
#
# def install_package(
#         package_type: constants.PackageType,
#         package_path: pl.Path
# ):
#     if package_type == constants.PackageType.DEB:
#         install_deb_package(package_path)
#     elif package_type == constants.PackageType.RPM:
#         install_rpm_package(package_path)
#     elif package_type == constants.PackageType.TAR:
#         install_tarball(package_path)
#     elif package_type == constants.PackageType.MSI:
#         install_msi_package(package_path)
#
#
# def _get_msi_install_path() -> pl.Path:
#     return pl.Path(os.environ["programfiles(x86)"]) / "Scalyr"
#
#
# def start_agent(package_type: constants.PackageType):
#     if package_type in [
#         constants.PackageType.DEB,
#         constants.PackageType.RPM,
#         constants.PackageType.MSI
#     ]:
#
#         if package_type == constants.PackageType.MSI:
#             # Add agent binaries to the PATH env. variable on windows.
#             bin_path = _get_msi_install_path() / "bin"
#             os.environ["PATH"] = f"{bin_path};{os.environ['PATH']}"
#
#         subprocess.check_call(f"scalyr-agent-2 start", shell=True, env=os.environ)
#     elif package_type == constants.PackageType.TAR:
#         tarball_dir = _get_tarball_install_path()
#
#         binary_path = tarball_dir / "bin/scalyr-agent-2"
#         subprocess.check_call([binary_path, "start"])
#
#
# def get_agent_status(package_type: constants.PackageType):
#     if package_type in [
#         constants.PackageType.DEB,
#         constants.PackageType.RPM,
#         constants.PackageType.TAR
#     ]:
#         subprocess.check_call(f"scalyr-agent-2 status -v", shell=True)
#     elif package_type == constants.PackageType.TAR:
#         tarball_dir = _get_tarball_install_path()
#
#         binary_path = tarball_dir / "bin/scalyr-agent-2"
#         subprocess.check_call([binary_path, "status", "-v"])
#
#
# def stop_agent(package_type: constants.PackageType):
#     if package_type in [
#         constants.PackageType.DEB,
#         constants.PackageType.RPM,
#         constants.PackageType.TAR
#     ]:
#         subprocess.check_call(f"scalyr-agent-2 stop", shell=True)
#     if package_type == constants.PackageType.TAR:
#         tarball_dir = _get_tarball_install_path()
#
#         binary_path = tarball_dir / "bin/scalyr-agent-2"
#         subprocess.check_call([binary_path, "stop"])
#
#
# def configure_agent(package_type: constants.PackageType, api_key: str):
#     if package_type in[
#         constants.PackageType.DEB,
#         constants.PackageType.RPM,
#     ]:
#         config_path = pathlib.Path(AGENT_CONFIG_PATH)
#     elif package_type == constants.PackageType.TAR:
#         install_path = _get_tarball_install_path()
#         config_path = install_path / "config/agent.json"
#     elif package_type == constants.PackageType.MSI:
#         config_path = _get_msi_install_path() / "config" / "agent.json"
#
#     config = {}
#     config["api_key"] = api_key
#
#     config["server_attributes"] = {"serverHost": "ARTHUR_TEST"}
#
#     # TODO enable and test system and process monitors
#     config["implicit_metric_monitor"] = False
#     config["implicit_agent_process_metrics_monitor"] = False
#     config["verify_server_certificate"] = False
#     config_path.write_text(json.dumps(config))
#
#
# def remove_deb_package():
#     env = os.environ.copy()
#
#     if __frozen__:
#         env[
#             "LD_LIBRARY_PATH"
#         ] = f'/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:{os.environ["LD_LIBRARY_PATH"]}'
#     subprocess.check_call(
#         f"apt-get remove -y scalyr-agent-2", shell=True,
#         env=env
#     )
#
#
# def remove_rpm_package():
#     env = os.environ.copy()
#
#     if __frozen__:
#         env["LD_LIBRARY_PATH"] = "/libx64"
#
#     subprocess.check_call(
#         f"yum remove -y scalyr-agent-2", shell=True,
#         env=env
#     )
#
#
# def remove_package(package_type: constants.PackageType):
#     if package_type == constants.PackageType.DEB:
#         remove_deb_package()
#     elif package_type == constants.PackageType.RPM:
#         remove_rpm_package()
#
#
# AGENT_CONFIG_PATH = "/etc/scalyr-agent-2/agent.json"
#
#
# def _get_logs_path(package_type: constants.PackageType) -> pl.Path:
#     if package_type in [
#         constants.PackageType.DEB,
#         constants.PackageType.RPM
#     ]:
#         return pl.Path("/var/log/scalyr-agent-2")
#     elif package_type == constants.PackageType.TAR:
#         return _get_tarball_install_path() / "log"
#     elif package_type == constants.PackageType.MSI:
#         return _get_msi_install_path() / "log"


def run(
        package_path: pl.Path,
        package_build_spec: build_and_test_specs.PackageBuildSpec,
        scalyr_api_key: str,
):
    if not package_path.exists():
        logging.error("No package.")
        exit(1)

    if package_build_spec.package_type == constants.PackageType.DEB:
        runner_cls = DebAgentRunner
    elif package_build_spec.package_type == constants.PackageType.RPM:
        runner_cls = RpmPAckageRunner
    elif package_build_spec.package_type == constants.PackageType.TAR:
        runner_cls = TarballAgentRunner

    agent_runner = runner_cls(
        package_path=package_path,
        package_build_spec=package_build_spec
    )

    agent_runner.install_package()

    agent_runner.configure_agent(
        api_key=scalyr_api_key
    )

    agent_runner.start_agent()

    time.sleep(2)

    agent_log_path = agent_runner.agent_log_path

    with agent_log_path.open("rb") as f:
        logging.info("Start verifying the agent.log file.")
        agent_log_verifier = LogVerifier()
        agent_log_verifier.set_new_content_getter(f.read)

        # Add check for any ERROR messages to the verifier.
        agent_log_verifier.add_line_check(AssertAgentLogLineIsNotAnErrorCheck())
        # Add check for the request stats message.
        agent_log_verifier.add_line_check(AgentLogRequestStatsLineCheck(), required_to_pass=True)

        # Start agent.log file verification.
        agent_log_verifier.verify(timeout=300)

        logging.info("Agent.log:")
        logging.info(agent_log_path.read_text())

    agent_runner.get_agent_status()

    time.sleep(2)

    agent_runner.stop_agent()

    agent_runner.remove_package()