#!/bin/bash

set -e

#if [ -n '' ] ; then
#  echo "1"
#else
#  echo "2"
#fi
#
#exit 0


SOURCE_ROOT=$(dirname "$(dirname "$(dirname "$0")")")

CACHE_DIR="${1}"

use_cache=false
save_cache=false

if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    mkdir -p "${CACHE_DIR}"
    save_cache=true
  else
    use_cache=true
  fi
fi

pip_cache_dir="$(pip cache dir)"

echo "PIP CACHE: ${pip_cache_dir}"

if $use_cache ; then
  mkdir -p ~/.cache
  cp -a "$CACHE_DIR/pip" "$pip_cache_dir"
fi

python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"

if $save_cache ; then
  cp -a "$pip_cache_dir" "$CACHE_DIR/pip"
fi