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

import sys
import shlex

# Fix some compatibility issues since our Release pipeline relies on a Python < 3.8
if sys.version_info < (3, 8):
    # Add join function to the shlex module if version of the Python < 3.8
    def shlex_join(args):
        return " ".join(shlex.quote(a) for a in args)

    shlex.join = shlex_join

    import logging

    original_logger_log = logging.Logger._log

    # monkey patch logger's _log method so it ignores 'stacklevel' argument.
    def logger_log(*args, stacklevel=None, **kwargs):
        return original_logger_log(*args, **kwargs)

    logging.Logger._log = logger_log
