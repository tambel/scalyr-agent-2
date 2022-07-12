# Copyright 2019 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# author: Edward Chee <echee@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

import stat
import os
import platform


def validate_docker_socket(socket_path):
    """
    Verify that the API unix socket exists and valid
    """
    if platform.system() == "Windows":
        # If we do not expect unix socket, then just return it as it is.
        # TODO maybe add existence check for Windows named pipes, but
        # it may require messing with direct WinAPI calls.
        return socket_path
    try:
        st = os.stat(socket_path)
        if stat.S_ISSOCK(st.st_mode):
            raise Exception()
    except Exception:
        raise Exception(
            "The file '%s' specified by the 'api_socket' configuration option does not exist or is not a "
            "socket.\n\tPlease make sure you have mapped the docker socket from the host to this container "
            "using the -v parameter.\n\tNote: Due to problems Docker has mapping symbolic links, you should "
            "specify the final file and not a path that contains a symbolic link, e.g. map /run/docker.sock "
            "rather than /var/run/docker.sock as on many unices /var/run is a symbolic link to "
            "the /run directory." % socket_path
        )


def get_full_api_socket_path_if_supported(path):
    """
    Return full docker UNIX socket or Windows named pipe path for the docker API socker.
    """
    if platform.system() == "Windows":

        return "npipe:\\\\%s" % path
    else:
        return "unix:/%s" % path
