#!/bin/bash
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

set -e

PARENT_DIR="$(dirname "$0")"
SOURCE_ROOT=$(dirname "$(dirname "$PARENT_DIR")")
source "$PARENT_DIR/cache_lib.sh"

#CACHE_DIR="${1}"

#use_cache=false
#save_cache=false
#
#if [ -n "$CACHE_DIR" ]; then
#  if [ ! -d "$CACHE_DIR" ]; then
#    mkdir -p "${CACHE_DIR}"
#    save_cache=true
#  else
#    use_cache=true
#  fi
#fi

pip_cache_dir="$(python3 -m pip cache dir)"

restore_from_cache pipi "$pip_cache_dir"

python3 -m pip install -r "${SOURCE_ROOT}/agent_build/requirement-files/main-requirements.txt"
python3 -m pip install -r "${SOURCE_ROOT}/agent_build/requirement-files/monitors-requirements.txt"
python3 -m pip install -r "${SOURCE_ROOT}/agent_build/requirement-files/compression-requirements.txt"
python3 -m pip install -r "${SOURCE_ROOT}/agent_build/requirement-files/frozen-binaries-requirements.txt"

#if $use_cache ; then
#  mkdir -p "$pip_cache_dir"
#  cp -a "$CACHE_DIR/pip/." "$pip_cache_dir"
#fi

save_to_cache pipi "$pip_cache_dir"


#
#if $save_cache ; then
#  cp -a "$pip_cache_dir" "$CACHE_DIR/pip"
#fi