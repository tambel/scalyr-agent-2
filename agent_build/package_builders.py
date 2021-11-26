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
This module defines all possible packages of the Scalyr Agent and how they can be built.
"""


import json
import pathlib as pl
import shlex
import tarfile
import abc
import shutil
import subprocess
import time
import sys
import stat
import uuid
import os
import re
import io
import platform
from typing import Union, Optional, List, Dict, Type


from agent_tools import constants
from agent_tools import environment_deployments
from agent_tools import build_in_docker

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    with pl.Path(destination).open("w") as dest_fp:
        for file_path in file_paths:
            with pl.Path(file_path).open("r") as in_fp:
                for line in in_fp:
                    if convert_newlines:
                        line.replace("\n", "\r\n")
                    dest_fp.write(line)


def recursively_delete_files_by_name(
    dir_path: Union[str, pl.Path], *file_names: Union[str, pl.Path]
):
    """Deletes any files that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    @param file_names: A variable number of strings containing regular expressions that should match the file names of
        the files that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for file_name in file_names:
        matchers.append(re.compile(str(file_name)))

    # Walk down the current directory.
    for root, dirs, files in os.walk(dir_path.absolute()):
        # See if any of the files at this level match any of the matchers.
        for file_path in files:
            for matcher in matchers:
                if matcher.match(file_path):
                    # Delete it if it did match.
                    os.unlink(os.path.join(root, file_path))
                    break


def recursively_delete_dirs_by_name(
        root_dir: Union[str, pl.Path], *dir_names: str
):
    """
    Deletes any directories that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    If a directory is found that needs to be deleted, all of it and its children are deleted.

    @param dir_names: A variable number of strings containing regular expressions that should match the file names of
        the directories that should be deleted.
    """

    # Compile the strings into actual regular expression match objects.
    matchers = []
    for dir_name in dir_names:
        matchers.append(re.compile(dir_name))

    # Walk down the file tree, top down, allowing us to prune directories as we go.
    for root, dirs, files in os.walk(root_dir):
        # Examine all directories at this level, see if any get a match
        for dir_path in dirs:
            for matcher in matchers:
                if matcher.match(dir_path):
                    shutil.rmtree(os.path.join(root, dir_path))
                    # Also, remove it from dirs so that we don't try to walk down it.
                    dirs.remove(dir_path)
                    break


class BadChangeLogFormat(Exception):
    pass


def parse_date(date_str):
    """Parses a date time string of the format MMM DD, YYYY HH:MM +ZZZZ and returns seconds past epoch.

    Example of the format is: Oct 10, 2014 17:00 -0700

    @param date_str: A string containing the date and time in the format described above.

    @return: The number of seconds past epoch.

    @raise ValueError: if there is a parsing problem.
    """
    # For some reason, it was hard to parse this particular format with the existing Python libraries,
    # especially when the timezone was not the same as the local time zone.  So, we have to do this the
    # sort of hard way.
    #
    # It is a little annoying that strptime only takes Sep for September and not Sep which is more common
    # in US-eng, so we cheat here and just swap it out.
    adjusted = date_str.replace("Sept", "Sep")

    # Find the timezone string at the end of the string.
    if re.search(r"[\-+]\d\d\d\d$", adjusted) is None:
        raise ValueError(
            "Value '%s' does not meet required time format of 'MMM DD, YYYY HH:MM +ZZZZ' (or "
            "as an example, ' 'Oct 10, 2014 17:00 -0700'" % date_str
        )

    # Use the existing Python string parsing calls to just parse the time and date.  We will handle the timezone
    # separately.
    try:
        base_time = time.mktime(time.strptime(adjusted[0:-6], "%b %d, %Y %H:%M"))
    except ValueError:
        raise ValueError(
            "Value '%s' does not meet required time format of 'MMM DD, YYYY HH:MM +ZZZZ' (or "
            "as an example, ' 'Oct 10, 2014 17:00 -0700'" % date_str
        )

    # Since mktime assumes the time is in localtime, we might have a different time zone
    # in tz_str, we must manually added in the difference.
    # First, convert -0700 to seconds.. the second two digits are the number of hours
    # and the last two are the minute of minutes.
    tz_str = adjusted[-5:]
    tz_offset_secs = int(tz_str[1:3]) * 3600 + int(tz_str[3:5]) * 60

    if tz_str.startswith("-"):
        tz_offset_secs *= -1

    # Determine the offset for the local timezone.
    if time.daylight:
        local_offset_secs = -1 * time.altzone
    else:
        local_offset_secs = -1 * time.timezone

    base_time += local_offset_secs - tz_offset_secs
    return base_time


def parse_change_log():
    """Parses the contents of CHANGELOG.md and returns the content in a structured way.

    @return: A list of dicts, one for each release in CHANGELOG.md.  Each release dict will have with several fields:
            name:  The name of the release
            version:  The version of the release
            packager:  The name of the packager, such as 'Steven Czerwinski'
            packager_email:  The email for the packager
            time:  The seconds past epoch when the package was created
            notes:  A list of strings or lists representing the notes for the release.  The list may
                have elements that are strings (for a single line of notes) or lists (for a nested list under
                the last string element).  Only three levels of nesting are allowed.
    """
    # Some regular expressions matching what we expect to see in CHANGELOG.md.
    # Each release section should start with a '##' line for major header.
    release_matcher = re.compile(r'## ([\d\._]+) "(.*)"')
    # The expected pattern we will include in a HTML comment to give information on the packager.
    packaged_matcher = re.compile(
        r"Packaged by (.*) <(.*)> on (\w+ \d+, \d+ \d+:\d\d [+-]\d\d\d\d)"
    )

    # Listed below are the deliminators we use to extract the structure from the changelog release
    # sections.  We fix our markdown syntax to make it easier for us.
    #
    # Our change log will look something like this:
    #
    # ## 2.0.1 "Aggravated Aardvark"
    #
    # New core features:
    # * Blah blah
    # * Blah Blah
    #   - sub point
    #
    # Bug fixes:
    # * Blah Blah

    # The deliminators, each level is marked by what pattern we should see in the next line to either
    # go up a level, go down a level, or confirm it is at the same level.
    section_delims = [
        # First level does not have any prefix.. just plain text.
        # So, the level up is the release header, which begins with '##'
        # The level down is ' *'.
        {
            "up": re.compile("## "),
            "down": re.compile(r"\* "),
            "same": re.compile(r"[^\s\*\-#]"),
            "prefix": "",
        },
        # Second level always begins with an asterisk.
        {
            "up": re.compile(r"[^\s\*\-#]"),
            "down": re.compile("    - "),
            "same": re.compile(r"\* "),
            "prefix": "* ",
        },
        # Third level always begins with '  -'
        {
            "up": re.compile(r"\* "),
            "down": None,
            "same": re.compile("    - "),
            "prefix": "    - ",
        },
    ]

    # Helper function.
    def read_section(lines, level=0):
        """Transforms the lines representing the notes for a single release into the desired nested representation.

        @param lines: The lines for the notes for a release including markup. NOTE, this list must be in reverse order,
            where the next line to be scanned is the last line in the list.
        @param level: The nesting level that these lines are at.

        @return: A list containing the notes, with nested lists as appropriate.
        """
        result = []

        if len(lines) == 0:
            return result

        while len(lines) > 0:
            # Go over each line, seeing based on its content, if we should go up a nesting level, down a level,
            # or just stay at the same level.
            my_line = lines.pop()

            # If the next line is at our same level, then just add it to our current list and continue.
            if section_delims[level]["same"].match(my_line) is not None:
                result.append(my_line[len(section_delims[level]["prefix"]) :])
                continue

            # For all other cases, someone else is going to have to look at this line, so add it back to the list.
            lines.append(my_line)

            # If the next line looks like it belongs any previous nesting levels, then we must have exited out of
            # our current nesting level, so just return what we have gathered for this sublist.
            for i in range(level + 1):
                if section_delims[i]["up"].match(my_line) is not None:
                    return result
            if (
                section_delims[level]["down"] is not None
                and section_delims[level]["down"].match(my_line) is not None
            ):
                # Otherwise, it looks like the next line belongs to a sublist.  Recursively call ourselves, going
                # down a level in nesting.
                result.append(read_section(lines, level + 1))
            else:
                raise BadChangeLogFormat(
                    "Release not line did not match expect format at level %d: %s"
                    % (level, my_line)
                )
        return result

    # Begin the real work here.  Read the change log.
    change_log_fp = open(os.path.join(__SOURCE_ROOT__, "CHANGELOG.md"), "r")

    try:
        # Skip over the first two lines since it should be header.
        change_log_fp.readline()
        change_log_fp.readline()

        # Read over all the lines, eliminating the comment lines and other useless things.  Also strip out all newlines.
        content = []
        in_comment = False
        for line in change_log_fp:
            line = line.rstrip()
            if len(line) == 0:
                continue

            # Check for a comment.. either beginning or closing.
            if line == "<!---":
                in_comment = True
            elif line == "--->":
                in_comment = False
            elif packaged_matcher.match(line) is not None:
                # The only thing we will pay attention to while in a comment is our packaged line.  If we see it,
                # grab it.
                content.append(line)
            elif not in_comment:
                # Keep any non-comments.
                content.append(line)

        change_log_fp.close()
        change_log_fp = None
    finally:
        if change_log_fp is not None:
            change_log_fp.close()

    # We reverse the content list so the first lines to be read are at the end.  This way we can use pop down below.
    content.reverse()

    # The list of release objects
    releases = []

    # The rest of the log should just contain release notes for each release.  Iterate over the content,
    # reading out the release notes for each release.
    while len(content) > 0:
        # Each release must begin with at least two lines -- one for the release name and then one for the
        # 'Packaged by Steven Czerwinski on... ' line that we pulled out of the HTML comment.
        if len(content) < 2:
            raise BadChangeLogFormat(
                "New release section does not contain at least two lines."
            )

        # Extract the information from each of those two lines.
        current_line = content.pop()
        release_version_name = release_matcher.match(current_line)
        if release_version_name is None:
            raise BadChangeLogFormat(
                "Header line for release did not match expected format: %s"
                % current_line
            )

        current_line = content.pop()
        packager_info = packaged_matcher.match(current_line)
        if packager_info is None:
            raise BadChangeLogFormat(
                "Packager line for release did not match expected format: %s"
                % current_line
            )

        # Read the section notes until we hit a '##' line.
        release_notes = read_section(content)

        try:
            time_value = parse_date(packager_info.group(3))
        except ValueError as err:
            message = getattr(err, "message", str(err))
            raise BadChangeLogFormat(message)

        releases.append(
            {
                "name": release_version_name.group(2),
                "version": release_version_name.group(1),
                "packager": packager_info.group(1),
                "packager_email": packager_info.group(2),
                "time": time_value,
                "notes": release_notes,
            }
        )

    return releases


class PackageBuilder(abc.ABC):
    """
        Base abstraction for all Scalyr agent package builders. it can perform build of the package directly on the
    current system or inside docker.
        It also uses ':py:module:`agent_tools.environment_deployments` features to define and deploy its build
        environment in order to be able to perform the actual build.
    """

    # Type of the package to build.
    PACKAGE_TYPE: constants.PackageType

    # Add agent source code as a bundled frozen binary if True, or
    # add the source code as it is.
    USE_FROZEN_BINARIES: bool = True

    # Specify the name of the frozen binary, if it is used.
    FROZEN_BINARY_FILE_NAME = "scalyr-agent-2"

    # The type of the installation. For more info, see the 'InstallType' in the scalyr_agent/__scalyr__.py
    INSTALL_TYPE: str

    # Map package-specific architecture names to the architecture names that are used in build.
    PACKAGE_FILENAME_ARCHITECTURE_NAMES: Dict[constants.Architecture, str] = {}

    # The format string for the glob that has to match result package filename.
    # For now, the format string accepts:
    #   {arch}: architecture of the package.
    # See more in the "filename_glob" property of the class.
    RESULT_PACKAGE_FILENAME_GLOB: str

    # Special global collection of all builders. It can be used by CI/CD scripts to find needed package builder.
    ALL_BUILDERS: Dict[str, 'PackageBuilder'] = {}

    def __init__(
            self,
            architecture: constants.Architecture,
            base_docker_image: str = None,
            deployment_step_classes: List[Type[environment_deployments.DeploymentStep]] = None,
            variant: str = None,
            no_versioned_file_name: bool = False,
    ):
        """
        :param architecture: Architecture of the package.
        :param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
        :param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.
        """
        # The path where the build output will be stored.
        self._build_output_path: Optional[pl.Path] = None

        # Folder with intermediate and temporary results of the build.
        self._intermediate_results_path: Optional[pl.Path] = None

        # The path of the folder where all files of the package will be stored.
        # May be help full for the debug purposes.
        self._package_files_path: Optional[pl.Path] = None

        self._variant = variant
        self._no_versioned_file_name = no_versioned_file_name

        self.architecture = architecture

        self.base_docker_image = base_docker_image

        # Create personal deployment for the package builder.
        self.deployment = environment_deployments.Deployment(
            name=self.name,
            step_classes=deployment_step_classes or [],
            architecture=architecture,
            base_docker_image=base_docker_image
        )

        PackageBuilder.ALL_BUILDERS[self.name] = self

    @property
    def name(self) -> str:
        """
        Unique name of the package builder. It considers the architecture of the package.
        """
        return f"{type(self).PACKAGE_TYPE.value}_{self.architecture.value}"

    @property
    def filename_glob(self) -> str:
        """
        Final glob that has to match result package filename.
        """

        # Get appropriate glob format string and apply the appropriate architecture.
        package_specific_arch_name = type(self).PACKAGE_FILENAME_ARCHITECTURE_NAMES.get(
            self.architecture, ''
        )
        return type(self).RESULT_PACKAGE_FILENAME_GLOB.format(
            arch=package_specific_arch_name
        )

    def build(
            self,
            output_path: Union[str, pl.Path],
            locally: bool = False
    ):
        """
        The function where the actual build of the package happens.
        :param output_path: Path to the directory where the resulting output has to be stored.
        :param locally: Force builder to build the package on the current system, even if meant to be done inside
            docker. This is needed to avoid loop when it is already inside the docker.
        """

        output_path = pl.Path(output_path).absolute()

        if output_path.exists():
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)

        # Build right here.
        if locally or not self.deployment.in_docker:
            self._build_output_path = pl.Path(output_path)
            self._package_files_path = self._build_output_path / "package_root"
            self._package_files_path.mkdir()
            self._intermediate_results_path = self._build_output_path / "intermediate_results"
            self._intermediate_results_path.mkdir()
            self._build(output_path=output_path)
            return

        # Build in docker.

        # First make sure that the deployment with needed images are ready.
        self.deployment.deploy()

        # To perform the build in docker we have to run the build_package.py script once more but in docker.
        build_package_script_path = pl.Path("/scalyr-agent-2/build_package.py")

        command_args = [
            "python3",
            str(build_package_script_path),
            self.name,
            "--output-dir",
            "/tmp/build",
            # Do not forget to specify this flag to avoid infinite docker build recursion.
            "--locally"
        ]

        command = shlex.join(command_args)

        # Run the docker build inside the result image of the deployment.
        base_image_name = self.deployment.result_image_name.lower()

        build_in_docker.build_stage(
            command=command,
            stage_name="build",
            architecture=self.architecture,
            image_name=f"agent-builder-{self.name}-{base_image_name}".lower(),
            base_image_name=base_image_name,
            output_path_mappings={output_path: pl.Path("/tmp/build")}
        )

    @property
    def _build_info(self) -> Optional[str]:
        """Returns a string containing the package build info."""

        build_info_buffer = io.StringIO()

        # We need to execute the git command in the source root.
        # Add in the e-mail address of the user building it.
        try:
            packager_email = (
                subprocess.check_output(
                    "git config user.email", shell=True, cwd=str(__SOURCE_ROOT__)
                )
                    .decode()
                    .strip()
            )
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

        # Determine the last commit from the log.
        commit_id = (
            subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
                shell=True,
                cwd=__SOURCE_ROOT__,
            )
                .decode()
                .strip()
        )

        print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

        # Include the branch just for safety sake.
        branch = (
            subprocess.check_output(
                "git branch | cut -d ' ' -f 2", shell=True, cwd=__SOURCE_ROOT__
            )
                .decode()
                .strip()
        )
        print("From branch: %s" % branch.strip(), file=build_info_buffer)

        # Add a timestamp.
        print(
            "Build time: %s"
            % str(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
            file=build_info_buffer,
        )

        return build_info_buffer.getvalue()

    @staticmethod
    def _add_config(
            config_source_path: Union[str, pl.Path], output_path: Union[str, pl.Path]
    ):
        """
        Copy config folder from the specified path to the target path.
        """
        config_source_path = pl.Path(config_source_path)
        output_path = pl.Path(output_path)
        # Copy config
        shutil.copytree(config_source_path, output_path)

        # Make sure config file has 640 permissions
        config_file_path = output_path / "agent.json"
        config_file_path.chmod(int("640", 8))

        # Make sure there is an agent.d directory regardless of the config directory we used.
        agent_d_path = output_path / "agent.d"
        agent_d_path.mkdir(exist_ok=True)
        # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
        # readable by others.
        agent_d_path.chmod(int("741", 8))

    @staticmethod
    def _add_certs(
            path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
    ):
        """
        Create needed certificates files in the specified path.
        """

        path = pl.Path(path)
        path.mkdir(parents=True)
        source_certs_path = __SOURCE_ROOT__ / "certs"

        cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

        if intermediate_certs:
            cat_files(
                source_certs_path.glob("*_intermediate.pem"),
                path / "intermediate_certs.pem",
            )
        if copy_other_certs:
            for cert_file in source_certs_path.glob("*.pem"):
                shutil.copy(cert_file, path / cert_file.name)

    @property
    def _package_version(self) -> str:
        """The version of the agent"""
        return pl.Path(__SOURCE_ROOT__, "VERSION").read_text().strip()

    def _build_frozen_binary(
            self,
            output_path: Union[str, pl.Path],
    ):
        """
        Build the frozen binary using the PyInstaller library.
        """
        output_path = pl.Path(output_path)

        # Create the special folder in the package output directory where the Pyinstaller's output will be stored.
        # That may be useful during the debugging.
        pyinstaller_output = self._intermediate_results_path / "frozen_binary"
        pyinstaller_output.mkdir(parents=True, exist_ok=True)

        scalyr_agent_package_path = __SOURCE_ROOT__ / "scalyr_agent"

        # Create package info file. It will be read by agent in order to determine the package type and install root.
        # See '__determine_install_root_and_type' function in scalyr_agent/__scalyr__.py file.
        package_info_file = self._intermediate_results_path / "package_info.json"

        package_info = {"install_type": type(self).INSTALL_TYPE}
        package_info_file.write_text(json.dumps(package_info))

        # Add this package_info file in the 'scalyr_agent' package directory, near the __scalyr__.py file.
        add_data = {
            str(package_info_file): "scalyr_agent"
        }

        # Add monitor modules as hidden imports, since they are not directly imported in the agent's code.
        hidden_imports = [
            "scalyr_agent.builtin_monitors.apache_monitor",
            "scalyr_agent.builtin_monitors.graphite_monitor",
            "scalyr_agent.builtin_monitors.mysql_monitor",
            "scalyr_agent.builtin_monitors.nginx_monitor",
            "scalyr_agent.builtin_monitors.shell_monitor",
            "scalyr_agent.builtin_monitors.syslog_monitor",
            "scalyr_agent.builtin_monitors.test_monitor",
            "scalyr_agent.builtin_monitors.url_monitor",
        ]

        # Add packages to frozen binary paths.
        paths_to_include = [
            str(scalyr_agent_package_path),
            str(scalyr_agent_package_path / "builtin_monitors")
        ]

        # Add platform specific things.
        if platform.system().lower().startswith("linux"):
            hidden_imports.extend([
                "scalyr_agent.builtin_monitors.linux_system_metrics",
                "scalyr_agent.builtin_monitors.linux_process_metrics",
            ])

            tcollectors_path = pl.Path(__SOURCE_ROOT__, "scalyr_agent", "third_party", "tcollector", "collectors")
            add_data.update({
                tcollectors_path: tcollectors_path.relative_to(__SOURCE_ROOT__)
            })
        elif platform.system().lower().startswith("win"):
            hidden_imports.extend([
                "scalyr_agent.builtin_monitors.windows_event_log_monitor",
                "scalyr_agent.builtin_monitors.windows_system_metrics",
                "scalyr_agent.builtin_monitors.windows_process_metrics",
            ])

        # Create --add-data options from previously added files.
        add_data_options = []
        for src, dest in add_data.items():
            add_data_options.append("--add-data")
            add_data_options.append(f"{src}{os.path.pathsep}{dest}")

        # Create --hidden-import options from previously created hidden imports list.
        hidden_import_options = []
        for h in hidden_imports:
            hidden_import_options.append("--hidden-import")
            hidden_import_options.append(str(h))

        dist_path = pyinstaller_output / "dist"

        # Run the PyInstaller.
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                str(scalyr_agent_package_path / "agent_main.py"),
                "--onefile",
                "--distpath", str(dist_path),
                "--workpath", str(pyinstaller_output / "build"),
                "-n", type(self).FROZEN_BINARY_FILE_NAME,
                "--paths", ":".join(paths_to_include),
                *add_data_options,
                *hidden_import_options,
                "--exclude-module", "asyncio",
                "--exclude-module", "FixTk",
                "--exclude-module", "tcl",
                "--exclude-module", "tk",
                "--exclude-module", "_tkinter",
                "--exclude-module", "tkinter",
                "--exclude-module", "Tkinter",
                "--exclude-module", "sqlite",

            ],
            cwd=str(__SOURCE_ROOT__)
        )

        frozen_binary_path = dist_path / type(self).FROZEN_BINARY_FILE_NAME
        # Make frozen binary executable.
        frozen_binary_path.chmod(frozen_binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        # Copy resulting frozen binary to the output.
        output_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen_binary_path, output_path)

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        """
        Build the basic structure for all packages.

            This creates a directory and then populates it with the basic structure required by most of the packages.

            It copies the certs, the configuration directories, etc.

            In the end, the structure will look like:
                certs/ca_certs.pem         -- The trusted SSL CA root list.
                bin/scalyr-agent-2         -- Main agent executable.
                bin/scalyr-agent-2-config  -- The configuration tool executable.
                build_info                 -- A file containing the commit id of the latest commit included in this package,
                                              the time it was built, and other information.
                VERSION                    -- File with current version of the agent.
                install_type               -- File with type of the installation.


        :param output_path: The output path where the result files are stored.
        """
        output_path = pl.Path(output_path)

        if output_path.exists():
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)

        # Write build_info file.
        build_info_path = output_path / "build_info"
        build_info_path.write_text(self._build_info)

        # Copy the monitors directory.
        monitors_path = output_path / "monitors"
        shutil.copytree(__SOURCE_ROOT__ / "monitors", monitors_path)
        recursively_delete_files_by_name(output_path / monitors_path, "README.md")

        # Add VERSION file.
        shutil.copy2(__SOURCE_ROOT__ / "VERSION", output_path / "VERSION")

        # Create bin directory with executables.
        bin_path = output_path / "bin"
        bin_path.mkdir()

        if type(self).USE_FROZEN_BINARIES:
            self._build_frozen_binary(bin_path)
        else:
            source_code_path = output_path / "py"

            shutil.copytree(__SOURCE_ROOT__ / "scalyr_agent", source_code_path / "scalyr_agent")

            agent_main_executable_path = bin_path / "scalyr-agent-2"
            agent_main_executable_path.symlink_to(pl.Path("..", "py", "scalyr_agent", "agent_main.py"))

            agent_config_executable_path = bin_path / "scalyr-agent-2-config"
            agent_config_executable_path.symlink_to(pl.Path("..", "py", "scalyr_agent", "agent_config.py"))

            # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
            recursively_delete_dirs_by_name(source_code_path, r"\.idea", "tests", "__pycache__")
            recursively_delete_files_by_name(
                source_code_path,
                r".*\.pyc", r".*\.pyo", r".*\.pyd", r"all_tests\.py", r".*~"
            )

    @abc.abstractmethod
    def _build(self, output_path: Union[str, pl.Path]):
        """
        The implementation of the package build.
        :param output_path: Path for the build result.
        """
        pass


class LinuxPackageBuilder(PackageBuilder):
    """
    The base package builder for all Linux packages.
    """

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        """
        Add files to the agent's install root which are common for all linux packages.
        """
        super(LinuxPackageBuilder, self)._build_package_files(output_path=output_path)

        # Add certificates.
        certs_path = output_path / "certs"
        self._add_certs(certs_path)

        # Misc extra files needed for some features.
        # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
        # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
        # using a package.
        misc_path = output_path / "misc"
        misc_path.mkdir()
        for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
            shutil.copy2(__SOURCE_ROOT__ / "docker" / f, misc_path / f)


class LinuxFhsBasedPackageBuilder(LinuxPackageBuilder):
    """
    The package builder for the packages which follow the Linux FHS structure.
    For example deb, rpm, docker and k8s images.
    """

    INSTALL_TYPE = "package"

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        # The install root is located in the usr/share/scalyr-agent-2.
        install_root = output_path / "usr/share/scalyr-agent-2"
        super(LinuxFhsBasedPackageBuilder, self)._build_package_files(
            output_path=install_root
        )

        pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
        pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

        bin_path = install_root / "bin"
        usr_sbin_path = self._package_files_path / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_symlink_path = (
                    self._package_files_path / "usr/sbin" / binary_path.name
            )
            symlink_target_path = pl.Path(
                "..", "share", "scalyr-agent-2", "bin", binary_path.name
            )
            binary_symlink_path.symlink_to(symlink_target_path)


class ContainerPackageBuilder(LinuxFhsBasedPackageBuilder):
    """
    The base builder for all docker and kubernetes based images . It builds an executable script in the current working
     directory that will build the container image for the various Docker and Kubernetes targets.
     This script embeds all assets it needs in it so it can be a standalone artifact. The script is based on
     `docker/scripts/container_builder_base.sh`. See that script for information on it can be used."
    """
    # Path to the configuration which should be used in this build.
    CONFIG_PATH = None
    # The file path for the Dockerfile to embed in the script, relative to the top of the agent source directory.
    DOCKERFILE_PATH = None

    # The name of the result image.
    RESULT_IMAGE_NAME = None

    # A list of repositories that should be added as tags to the image once it is built.
    # Each repository will have two tags added -- one for the specific agent version and one for `latest`.
    IMAGE_REPOS = None

    USE_FROZEN_BINARIES = False

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        super(ContainerPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Need to create some docker specific directories.
        pl.Path(output_path / "var/log/scalyr-agent-2/containers").mkdir()

        # Copy config
        self._add_config(type(self).CONFIG_PATH, self._package_files_path / "etc/scalyr-agent-2")

    def _build(self, output_path: Union[str, pl.Path]):
        self._build_package_files(
            output_path=self._package_files_path
        )

        container_tarball_path = self._intermediate_results_path / "scalyr-agent.tar.gz"

        # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
        # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
        # mainly Posix.
        with tarfile.open(container_tarball_path, "w:gz") as container_tar:

            for root, dirs, files in os.walk(self._package_files_path):
                to_copy = []
                for name in dirs:
                    to_copy.append(os.path.join(root, name))
                for name in files:
                    to_copy.append(os.path.join(root, name))

                for x in to_copy:
                    file_entry = container_tar.gettarinfo(
                        x, arcname=str(pl.Path(x).relative_to(self._package_files_path))
                    )
                    file_entry.uname = "root"
                    file_entry.gname = "root"
                    file_entry.uid = 0
                    file_entry.gid = 0

                    if file_entry.isreg():
                        with open(x, "rb") as fp:
                            container_tar.addfile(file_entry, fp)
                    else:
                        container_tar.addfile(file_entry)

        # Tar it up but hold the tarfile in memory.  Note, if the source tarball really becomes massive, might have to
        # rethink this.
        tar_out = io.BytesIO()
        with tarfile.open("assets.tar.gz", "w|gz", tar_out) as tar:
            # Add dockerfile.
            tar.add(str(type(self).DOCKERFILE_PATH), arcname="Dockerfile")
            # Add requirement files.
            tar.add(str(_AGENT_BUILD_PATH / "requirements.txt"), arcname="requirements.txt")
            tar.add(
                str(_AGENT_BUILD_PATH / "linux/k8s_and_docker/docker-and-k8s-requirements.txt"),
                arcname="docker-and-k8s-requirements.txt"
            )
            # Add container source tarball.
            tar.add(container_tarball_path, arcname="scalyr-agent.tar.gz")

        if self._variant is None:
            version_string = self._package_version
        else:
            version_string = "%s.%s" % (self._package_version, self._variant)

        builder_name = f"scalyr-agent-{type(self).PACKAGE_TYPE}"
        if self._no_versioned_file_name:
            output_name = builder_name
        else:
            output_name = "%s-%s" % (builder_name, version_string)

        # Read the base builder script into memory
        base_script_path = __SOURCE_ROOT__ / "docker/scripts/container_builder_base.sh"
        base_script = base_script_path.read_text()

        # The script has two lines defining environment variables (REPOSITORIES and TAGS) that we need to overwrite to
        # set them to what we want.  We'll just do some regex replace to do that.
        base_script = re.sub(
            r"\n.*OVERRIDE_REPOSITORIES.*\n",
            '\nREPOSITORIES="%s"\n' % ",".join(type(self).IMAGE_REPOS),
            base_script,
        )
        base_script = re.sub(
            r"\n.*OVERRIDE_TAGS.*\n",
            '\nTAGS="%s"\n' % "%s,latest" % version_string,
            base_script,
        )

        # Write one file that has the contents of the script followed by the contents of the tarfile.
        builder_script_path = self._build_output_path / output_name
        with builder_script_path.open("wb") as f:
            f.write(base_script.encode("utf-8"))

            f.write(tar_out.getvalue())

        # Make the script executable.
        st = builder_script_path.stat()
        builder_script_path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP)


class K8sPackageBuilder(ContainerPackageBuilder):
    """
    An image for running the agent on Kubernetes.
    """
    PACKAGE_TYPE = "k8s"
    TARBALL_NAME = "scalyr-k8s-agent.tar.gz"
    CONFIG_PATH = __SOURCE_ROOT__ / "docker/k8s-config"
    DOCKERFILE_PATH = __SOURCE_ROOT__ / "docker/Dockerfile.k8s"
    RESULT_IMAGE_NAME = "scalyr-k8s-agent"
    IMAGE_REPOS = ["scalyr/scalyr-k8s-agent"]


class DockerJsonPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to fetch logs via the file system (the container log
    directory is mounted to the agent container.)  This is the preferred way of running on Docker.
    This image is published to scalyr/scalyr-agent-docker-json.
    """
    PACKAGE_TYPE = "docker-json"
    TARBALL_NAME = "scalyr-docker-agent.tar.gz"
    CONFIG_PATH = __SOURCE_ROOT__ / "docker/docker-json-config"
    DOCKERFILE_PATH = __SOURCE_ROOT__ / "docker/Dockerfile"
    RESULT_IMAGE_NAME = "scalyr-docker-agent-json"
    IMAGE_REPOS = ["scalyr/scalyr-agent-docker-json"]


class DockerSyslogPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to receive logs from other containers via syslog.
    This is the deprecated approach (but is still published under scalyr/scalyr-docker-agent for
    backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog to help
    with the eventual migration.
    """
    PACKAGE_TYPE = "docker-syslog"
    TARBALL_NAME = "scalyr-docker-agent.tar.gz"
    CONFIG_PATH = __SOURCE_ROOT__ / "docker/docker-syslog-config"
    DOCKERFILE_PATH = __SOURCE_ROOT__ / "docker/Dockerfile.syslog"
    RESULT_IMAGE_NAME = "scalyr-docker-agent-syslog"
    IMAGE_REPOS = ["scalyr/scalyr-agent-docker-syslog", "scalyr/scalyr-agent-docker"]


class DockerApiPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to fetch logs via the Docker API using docker_raw_logs: false
    configuration option.
    """
    PACKAGE_TYPE = "docker-api"
    TARBALL_NAME = "scalyr-docker-agent.tar.gz"
    CONFIG_PATH = __SOURCE_ROOT__ / "docker/docker-api-config"
    DOCKERFILE_PATH = __SOURCE_ROOT__ / "docker/Dockerfile"
    RESULT_IMAGE_NAME = "scalyr-docker-agent-api"
    IMAGE_REPOS = ["scalyr/scalyr-agent-docker-api"]


class FpmBasedPackageBuilder(LinuxFhsBasedPackageBuilder):
    """
    Base image builder for packages which are produced by the 'fpm' packager.
    For example dep, rpm.
    """
    INSTALL_TYPE = "package"

    # Which type of the package the fpm package has to produce.
    FPM_PACKAGE_TYPE: str

    def __init__(
            self,
            architecture,
            base_docker_image: str = None,
            deployment_step_classes: List[Type[environment_deployments.DeploymentStep]] = None,
            variant: str = None,
            no_versioned_file_name: bool = False,
    ):
        super(FpmBasedPackageBuilder, self).__init__(
            architecture=architecture,
            base_docker_image=base_docker_image,
            deployment_step_classes=deployment_step_classes,
            variant=variant, no_versioned_file_name=no_versioned_file_name,
        )
        # Path to generated changelog files.
        self._package_changelogs_path: Optional[pl.Path] = None

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        super(FpmBasedPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Copy config
        self._add_config(__SOURCE_ROOT__ / "config", output_path / "etc/scalyr-agent-2")

        # Copy the init.d script.
        init_d_path = output_path / "etc/init.d"
        init_d_path.mkdir(parents=True)
        shutil.copy2(
            _AGENT_BUILD_PATH / "linux/deb_or_rpm/files/init.d/scalyr-agent-2",
            init_d_path / "scalyr-agent-2",
        )

    def _build(
            self,
            output_path: Union[str, pl.Path],
    ):
        """
        Build the deb or rpm package using the 'fpm' pckager.
        :param output_path: The path where the result package is stored.
        """

        self._build_package_files(output_path=self._package_files_path)

        if self._variant is not None:
            iteration_arg = "--iteration 1.%s" % self._variant
        else:
            iteration_arg = ""

        install_scripts_path = _AGENT_BUILD_PATH / "linux/deb_or_rpm/install-scripts"

        # generate changelogs
        self.create_change_logs()

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics and "
            "log files and transmit them to Scalyr."
        )

        # filename = f"scalyr-agent-2_{self._package_version}_{arch}.{ext}"

        # fmt: off
        fpm_command = [
            "fpm",
            "-s", "dir",
            "-a", self.PACKAGE_FILENAME_ARCHITECTURE_NAMES[self.architecture],
            "-t", self.FPM_PACKAGE_TYPE,
            "-n", "scalyr-agent-2",
            "-v", self._package_version,
            "--chdir", str(self._package_files_path),
            "--license", "Apache 2.0",
            "--vendor", f"Scalyr {iteration_arg}",
            "--maintainer", "czerwin@scalyr.com",
            "--provides", "scalyr-agent-2",
            "--description", description,
            "--depends", 'bash >= 3.2',
            "--url", "https://www.scalyr.com",
            "--deb-user", "root",
            "--deb-group", "root",
            "--deb-changelog", str(self._package_changelogs_path / 'changelog-deb'),
            "--rpm-changelog", str(self._package_changelogs_path / 'changelog-rpm'),
            "--rpm-user", "root",
            "--rpm-group", "root",
            "--after-install", str(install_scripts_path / 'postinstall.sh'),
            "--before-remove", str(install_scripts_path / 'preuninstall.sh'),
            "--deb-no-default-config-files",
            "--no-deb-auto-config-files",
            "--config-files", "/etc/scalyr-agent-2/agent.json",
            "--directories", "/usr/share/scalyr-agent-2",
            "--directories", "/var/lib/scalyr-agent-2",
            "--directories", "/var/log/scalyr-agent-2",
            # NOTE 1: By default fpm won't preserve all the permissions we set on the files so we need
            # to use those flags.
            # If we don't do that, fpm will use 77X for directories and we don't really want 7 for
            # "group" and it also means config file permissions won't be correct.
            # NOTE 2: This is commented out since it breaks builds produced on builder VM where
            # build_package.py runs as rpmbuilder user (uid 1001) and that uid is preserved as file
            # owner for the package tarball file which breaks things.
            # On Circle CI uid of the user under which the package job runs is 0 aka root so it works
            # fine.
            # We don't run fpm as root on builder VM which means we can't use any other workaround.
            # Commenting this flag out means that original file permissions (+ownership) won't be
            # preserved which means we will also rely on postinst step fixing permissions for fresh /
            # new installations since those permissions won't be correct in the package artifact itself.
            # Not great.
            # Once we move all the build steps to Circle CI and ensure build_package.py runs as uid 0
            # we should uncomment this.
            # In theory it should work wth --*-user fpm flag, but it doesn't. Keep in mind that the
            # issue only applies to deb packages since --rpm-user and --rpm-root flag override the user
            # even if the --rpm-use-file-permissions flag is used.
            # "  --rpm-use-file-permissions "
            "--rpm-use-file-permissions",
            "--deb-use-file-permissions",
            # NOTE: Sadly we can't use defattrdir since it breakes permissions for some other
            # directories such as /etc/init.d and we need to handle that in postinst :/
            # "  --rpm-auto-add-directories "
            # "  --rpm-defattrfile 640"
            # "  --rpm-defattrdir 751"
            # "  -C root usr etc var",
        ]
        # fmt: on

        # Run fpm command and build the package.
        subprocess.check_call(
            fpm_command,
            cwd=str(self._build_output_path),
        )

    def create_change_logs(self):
        """Creates the necessary change logs for both RPM and Debian based on CHANGELOG.md.

        Creates two files named 'changelog-rpm' and 'changelog-deb'.  They
        will have the same content as CHANGELOG.md but formatted by the respective standards for the different
        packaging systems.
        """

        # We define a helper function named print_release_notes that is used down below.
        def print_release_notes(output_fp, notes, level_prefixes, level=0):
            """Emits the notes for a single release to output_fp.

            @param output_fp: The file to write the notes to
            @param notes: An array of strings containing the notes for the release. Some elements may be lists of strings
                themselves to represent sublists. Only three levels of nested lists are allowed. This is the same format
                returned by parse_change_log() method.
            @param level_prefixes: The prefix to use for each of the three levels of notes.
            @param level: The current level in the notes.
            """
            prefix = level_prefixes[level]
            for note in notes:
                if isinstance(note, list):
                    # If a sublist, then recursively call this function, increasing the level.
                    print_release_notes(output_fp, note, level_prefixes, level + 1)
                    if level == 0:
                        print("", file=output_fp)
                else:
                    # Otherwise emit the note with the prefix for this level.
                    print("%s%s" % (prefix, note), file=output_fp)

        self._package_changelogs_path = self._build_output_path / "package_changelog"
        self._package_changelogs_path.mkdir()

        # Handle the RPM log first.  We parse CHANGELOG.md and then emit the notes in the expected format.
        fp = open(self._package_changelogs_path / "changelog-rpm", "w")
        try:
            for release in parse_change_log():
                date_str = time.strftime("%a %b %d %Y", time.localtime(release["time"]))

                # RPM expects the leading line for a relesae to start with an asterisk, then have
                # the name of the person doing the release, their e-mail and then the version.
                print(
                    "* %s %s <%s> %s"
                    % (
                        date_str,
                        release["packager"],
                        release["packager_email"],
                        release["version"],
                    ),
                    file=fp,
                )
                print("", file=fp)
                print(
                    "Release: %s (%s)" % (release["version"], release["name"]), file=fp
                )
                print("", file=fp)
                # Include the release notes, with the first level with no indent, an asterisk for the second level
                # and a dash for the third.
                print_release_notes(fp, release["notes"], ["", " * ", "   - "])
                print("", file=fp)
        finally:
            fp.close()

        # Next, create the Debian change log.
        fp = open(self._package_changelogs_path / "changelog-deb", "w")
        try:
            for release in parse_change_log():
                # Debian expects a leading line that starts with the package, including the version, the distribution
                # urgency.  Then, anything goes until the last line for the release, which begins with two dashes.
                date_str = time.strftime(
                    "%a, %d %b %Y %H:%M:%S %z", time.localtime(release["time"])
                )
                print(
                    "scalyr-agent-2 (%s) stable; urgency=low" % release["version"],
                    file=fp,
                )
                # Include release notes with an indented first level (using asterisk, then a dash for the next level,
                # finally a plus sign.
                print_release_notes(fp, release["notes"], ["  * ", "   - ", "     + "])
                print(
                    " -- %s <%s>  %s"
                    % (
                        release["packager"],
                        release["packager_email"],
                        date_str,
                    ),
                    file=fp,
                )
        finally:
            fp.close()


class DebPackageBuilder(FpmBasedPackageBuilder):
    PACKAGE_TYPE = constants.PackageType.DEB
    PACKAGE_FILENAME_ARCHITECTURE_NAMES = {
        constants.Architecture.X86_64: "amd64",
        constants.Architecture.ARM64: "arm64"
    }
    RESULT_PACKAGE_FILENAME_GLOB = "scalyr-agent-2_*.*.*_{arch}.deb"
    FPM_PACKAGE_TYPE = "deb"


class RpmPackageBuilder(FpmBasedPackageBuilder):
    PACKAGE_TYPE = constants.PackageType.RPM
    PACKAGE_FILENAME_ARCHITECTURE_NAMES = {
        constants.Architecture.X86_64: "x86_64",
        constants.Architecture.ARM64: "aarch64"
    }
    RESULT_PACKAGE_FILENAME_GLOB = "scalyr-agent-2-*.*.*-1.{arch}.rpm"
    FPM_PACKAGE_TYPE = "rpm"


class TarballPackageBuilder(LinuxPackageBuilder):
    """
    The builder for the tarball packages.
    """

    PACKAGE_TYPE = constants.PackageType.TAR
    INSTALL_TYPE = "packageless"
    PACKAGE_FILENAME_ARCHITECTURE_NAMES = {
        constants.Architecture.X86_64: constants.Architecture.X86_64.value,
        constants.Architecture.ARM64: constants.Architecture.ARM64.value
    }
    RESULT_PACKAGE_FILENAME_GLOB = "scalyr-agent-*.*.*_{arch}.tar.gz"

    def _build_package_files(self, output_path: Union[str, pl.Path]):

        super(TarballPackageBuilder, self)._build_package_files(output_path=output_path)

        # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
        # in the tarball itself where the running process will store its state.
        data_dir = output_path / "data"
        data_dir.mkdir()
        log_dir = output_path / "log"
        log_dir.mkdir()

        self._add_config(__SOURCE_ROOT__ / "config", output_path / "config")

    def _build(self, output_path: Union[str, pl.Path]):

        self._build_package_files(
            output_path=self._package_files_path,
        )

        # Build frozen binary.
        bin_path = self._package_files_path / "bin"
        self._build_frozen_binary(bin_path)

        if self._variant is None:
            version_string = self._package_version
        else:
            version_string = f"{self._package_version}.{self._variant}"

        base_archive_name = f"scalyr-agent"

        if self._no_versioned_file_name:
            output_name = f"{base_archive_name}_{self.architecture.value}.tar.gz"
        else:
            output_name = f"{base_archive_name}-{version_string}_{self.architecture.value}.tar.gz"

        tarball_output_path = self._build_output_path / output_name

        # Tar it up.
        tar = tarfile.open(tarball_output_path, "w:gz")
        tar.add(self._package_files_path, arcname=base_archive_name)
        tar.close()


class MsiWindowsPackageBuilder(PackageBuilder):
    PACKAGE_TYPE = constants.PackageType.MSI
    INSTALL_TYPE = "package"
    FROZEN_BINARY_FILE_NAME = "scalyr-agent-2.exe"
    RESULT_PACKAGE_FILENAME_GLOB = "ScalyrAgentInstaller-*.*.*.msi"

    # A GUID representing Scalyr products, used to generate a per-version guid for each version of the Windows
    # Scalyr Agent.  DO NOT MODIFY THIS VALUE, or already installed software on clients machines will not be able
    # to be upgraded.
    _scalyr_guid_ = uuid.UUID("{0b52b8a0-22c7-4d50-92c1-8ea3b258984e}")

    @property
    def _package_version(self) -> str:
        # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
        # requires X.X.X.X.  So, we convert if necessary.
        base_version = super(MsiWindowsPackageBuilder, self)._package_version
        if len(base_version.split(".")) == 5:
            parts = base_version.split(".")
            del parts[3]
            version = ".".join(parts)
            return version

        return base_version

    def _build(self, output_path: Union[str, pl.Path]):

        scalyr_dir = self._package_files_path / "Scalyr"

        # Build common package files.
        self._build_package_files(output_path=scalyr_dir)

        # Add root certificates.
        certs_path = scalyr_dir / "certs"
        self._add_certs(certs_path, intermediate_certs=False, copy_other_certs=False)

        bin_path = scalyr_dir / "bin"
        # # Build frozen binaries and copy them into bin folder.

        # filename = "scalyr-agent-2.exe"
        # self._build_frozen_binary(
        #     bin_path,
        # )

        shutil.copy2(
            bin_path / type(self).FROZEN_BINARY_FILE_NAME,
            bin_path / "ScalyrAgentService.exe"
        )

        shutil.copy(_AGENT_BUILD_PATH / "windows/files/ScalyrShell.cmd", bin_path)
        shutil.copy(_AGENT_BUILD_PATH / "windows/files/scalyr-agent-2-config.cmd", bin_path)

        # Copy config template.
        config_templates_dir_path = pl.Path(scalyr_dir / "config" / "templates")
        config_templates_dir_path.mkdir(parents=True)
        config_template_path = config_templates_dir_path / "agent_config.tmpl"
        shutil.copy2(__SOURCE_ROOT__ / "config" / "agent.json", config_template_path)
        config_template_path.write_text(
            config_template_path.read_text().replace("\n", "\r\n")
        )

        if self._variant is None:
            variant = "main"
        else:
            variant = self._variant

        # Generate a unique identifier used to identify this version of the Scalyr Agent to windows.
        product_code = uuid.uuid3(
            type(self)._scalyr_guid_,
            "ProductID:%s:%s" % (variant, self._package_version),
        )
        # The upgrade code identifies all families of versions that can be upgraded from one to the other.  So, this
        # should be a single number for all Scalyr produced ones.
        upgrade_code = uuid.uuid3(type(self)._scalyr_guid_, "UpgradeCode:%s" % variant)

        wix_package_output = self._build_output_path / "wix"
        wix_package_output.mkdir(parents=True)

        wixobj_file_path = wix_package_output / "ScalyrAgent.wixobj"

        wxs_file_path = _AGENT_BUILD_PATH / "windows/scalyr_agent.wxs"

        # Compile WIX .wxs file.
        subprocess.check_call(
            [
                "candle",
                "-nologo",
                "-out",
                str(wixobj_file_path),
                f"-dVERSION={self._package_version}",
                f"-dUPGRADECODE={upgrade_code}",
                f"-dPRODUCTCODE={product_code}",
                str(wxs_file_path),
            ]
        )

        installer_name = f"ScalyrAgentInstaller-{self._package_version}.msi"
        installer_path = self._build_output_path / installer_name

        # Link compiled WIX files into msi installer.
        subprocess.check_call(
            [
                "light",
                "-nologo",
                "-ext",
                "WixUtilExtension.dll",
                "-ext",
                "WixUIExtension",
                "-out",
                str(installer_path),
                str(wixobj_file_path),
                "-v",
            ],
            cwd=str(scalyr_dir.absolute().parent),
        )


_DEFAULT_LINUX_BUILDERS_BASE_DOCKER_IMAGE = "centos:6"

_DEFAULT_LINUX_BUILDER_DEPLOYMENT_STEPS = [
    environment_deployments.InstallPythonStep,
    environment_deployments.InstallBuildRequirementsStep
]

DEB_X86_64_BUILDER = DebPackageBuilder(
    architecture=constants.Architecture.X86_64,
    base_docker_image=_DEFAULT_LINUX_BUILDERS_BASE_DOCKER_IMAGE,
    deployment_step_classes=_DEFAULT_LINUX_BUILDER_DEPLOYMENT_STEPS,
)

RPM_X86_64_BUILDER = RpmPackageBuilder(
    architecture=constants.Architecture.X86_64,
    base_docker_image=_DEFAULT_LINUX_BUILDERS_BASE_DOCKER_IMAGE,
    deployment_step_classes=_DEFAULT_LINUX_BUILDER_DEPLOYMENT_STEPS,
)

TAR_x86_64_BUILDER = TarballPackageBuilder(
    architecture=constants.Architecture.X86_64,
    base_docker_image=_DEFAULT_LINUX_BUILDERS_BASE_DOCKER_IMAGE,
    deployment_step_classes=_DEFAULT_LINUX_BUILDER_DEPLOYMENT_STEPS
)


_WINDOWS_BUILDER_DEPLOYMENT_STEPS = [
    environment_deployments.InstallWindowsBuilderToolsStep,
    environment_deployments.InstallBuildRequirementsStep
]

# Widnows MSI Packages. Only support X86 architecture for now.
MSI_x86_64_BUILDER = MsiWindowsPackageBuilder(
    architecture=constants.Architecture.X86_64,
    deployment_step_classes=_WINDOWS_BUILDER_DEPLOYMENT_STEPS
)


# # Name of the docker image that has to be used as a base image for all linux base packages.
# _LINUX_SPECS_BASE_IMAGE = "centos:7"
#
# # The architectures types that we support for linux packages.
# _DEFAULT_PACKAGE_ARCHITECTURES = [
#     constants.Architecture.X86_64, constants.Architecture.ARM64
# ]
#
# # Create package build specs for the DEB package. Since we pass 2 architectures, then we get two different build specs.
# DEB_x86_64, DEB_ARM64 = PackageBuildSpec.create_package_build_specs(
#     package_type=constants.PackageType.DEB,
#     package_builder_cls=DebPackageBuilder,
#     filename_glob_format="scalyr-agent-2_*.*.*_{arch}.deb",
#     deployment=environment_deployments.LINUX_PACKAGE_BUILDER_DEPLOYMENT,
#     base_docker_image=_LINUX_SPECS_BASE_IMAGE,
#     architectures=_DEFAULT_PACKAGE_ARCHITECTURES
# )
#
# # The same, but for the RPM packages.
# RPM_x86_64, RPM_ARM64 = PackageBuildSpec.create_package_build_specs(
#     package_type=constants.PackageType.RPM,
#     package_builder_cls=RpmPackageBuilder,
#     filename_glob_format="scalyr-agent-2-*.*.*-*.{arch}.rpm",
#     deployment=environment_deployments.LINUX_PACKAGE_BUILDER_DEPLOYMENT,
#     base_docker_image=_LINUX_SPECS_BASE_IMAGE,
#     architectures=_DEFAULT_PACKAGE_ARCHITECTURES
# )
#
# # Tar packages.
# TAR_x86_64, TAR_ARM64 = PackageBuildSpec.create_package_build_specs(
#     package_type=constants.PackageType.TAR,
#     package_builder_cls=TarballPackageBuilder,
#     filename_glob_format="scalyr-agent-*.*.*_{arch}.tar.gz",
#     deployment=environment_deployments.LINUX_PACKAGE_BUILDER_DEPLOYMENT,
#     base_docker_image=_LINUX_SPECS_BASE_IMAGE,
#     architectures=_DEFAULT_PACKAGE_ARCHITECTURES
# )


