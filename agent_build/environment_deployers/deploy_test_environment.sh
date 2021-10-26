SOURCE_ROOT=$(dirname "$(dirname "$(dirname "$0")")")

CACHE_DIR="${1}"

use_cache=false

if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    >&2 echo "Cache directory '${CACHE_DIR}' does not exist."
    exit 1
    use_cache=true
  fi
fi

if $use_cache ; then
  cp -a "$CACHE_DIR/pip" ~/.cache/pip
fi

python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"