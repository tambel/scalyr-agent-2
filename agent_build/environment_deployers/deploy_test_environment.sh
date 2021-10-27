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

python3 --version
pip_cache_dir="$(python3 -m pip cache dir)"

echo "PIP CACHE: ${pip_cache_dir}"

ls "$CACHE_DIR"

echo "FFFFF"

if $use_cache ; then
  mkdir -p "$pip_cache_dir"
  cp -a "$CACHE_DIR/pip/." "$pip_cache_dir"
fi

python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"

if $save_cache ; then
  echo "Save pip cache."
  ls "$pip_cache_dir"
  cp -a "$pip_cache_dir" "$CACHE_DIR/pip"
  echo "-------"
  ls "$CACHE_DIR"
  echo "-----"
  ls "$CACHE_DIR/pip"
fi