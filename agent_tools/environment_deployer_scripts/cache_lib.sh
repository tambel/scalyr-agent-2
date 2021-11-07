set -e

CACHE_DIR="$1"


if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    mkdir -p "${CACHE_DIR}"
  fi
  echo "Use dir ${CACHE_DIR} as cache."
  use_cache=true
else
  use_cache=false
fi




function restore_from_cache() {
  if ! $use_cache ; then
    echo "Cache disabled."
    return 0
  fi
  name=$1
  path=$2

  full_path="${CACHE_DIR}/${name}"


  if [ -d "${full_path}" ]; then
    echo "Directory ${name} in cache. Reuse it."
    cp -a "${full_path}/." "${path}"

  else
    echo "Directory ${name} not in cache"
  fi
  if [ -f "${full_path}" ]; then
    echo "File ${name} in cache. Reuse it."
    cp -a "${full_path}" "${path}"

  else
    echo "File ${name} not in cache"
  fi
}

function save_to_cache() {
  name=$1
  path=$2

  if ! $use_cache ; then
    echo "Cache disabled"
    return 0
  fi

  full_path="${CACHE_DIR}/${name}"

  if [ -f "${path}" ]; then
    if [ ! -f "${full_path}" ]; then
      echo "File ${path} saved to cache"
      cp -a "${path}" "${full_path}"
    else
      echo "File ${path} not saved to cache"
    fi
  else
    if [ ! -d "${full_path}" ]; then
      echo "Dir saved to cache"
      cp -a "${path}/." "${full_path}"

    else
      echo "Dir not saved to cache"
    fi
  fi



}