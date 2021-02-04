#!/usr/bin/env bash
#
# Copyright 2014-2020 Scalyr Inc.
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
#
# =========================================================================
#
# This script is used to create installer script fot  the scalyr agent.
# It also creates packages with the  repository configuration.
#
# Usage: create-agent-installer.sh <REPO_BASE_URL>

set -e;

function die() {
  echo "$1";
  exit 1;
}


set -e


if [ -z "$1" ]; then
  die "You must provide the repository type. Possible values: 'stable', 'beta', 'internal'.";
fi



SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

REPO_BASE_URL=$1


set -e

REPOSITORY_URL="https://scalyr-repo.s3.amazonaws.com/$REPO_BASE_URL"

PUBLIC_KEY_URL="https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x84AC559B5FB5463885CE0841F70CEEDB4AD7B6C6"

# create a yum repo spec data.
YUM_REPO_SPEC=$(cat << EOM
[scalyr]
includepkgs=scalyr-agent,scalyr-agent-2,scalyr-repo
name=Scalyr packages - noarch
baseurl=https://scalyr-repo.s3.amazonaws.com/$RELEASE_REPO_BASE_URL/yum/binaries/noarch
mirror_expire=300
metadata_expire=300
enabled=1
gpgcheck=1
gpgkey=${PUBLIC_KEY_URL}
EOM
)

echo "Create Scalyr yum repo spec file."
echo "${YUM_REPO_SPEC}" > "scalyr.repo"

# we need to escape the ampersand in order to be able use this text as a replacement part for the awk.
YUM_REPO_SPEC=${YUM_REPO_SPEC//&/\\\\&}

PUBLIC_KEY="$(curl -s "${PUBLIC_KEY_URL}")"

install_script_text="$(cat "$SCRIPTPATH/installScalyrAgentV2.sh")"

# replace a special placeholder for the repository type in the install sript to determine a final URL of the repository.
install_script_text="$(awk -v url="$REPOSITORY_URL" '{sub("{ % REPLACE_REPOSITORY_URL % }", url); print}' <<<"$install_script_text")"

# replace a special placeholder for the yum spec file.
install_script_text="$(awk -v spec="$YUM_REPO_SPEC" '{sub("{ % REPLACE_YUM_REPO_SPEC % }", spec); print}' <<<"$install_script_text")"

# replace a special placeholder for the public key url.
install_script_text="$(awk -v key="$PUBLIC_KEY" '{sub("{ % REPLACE_PUBLIC_KEY % }", key); print}' <<<"$install_script_text")"

# also remove all special comments which are usefull only for template but not for the resulting file.
install_script_text="$(awk '{sub("# { #.*# }", ""); print}' <<<"$install_script_text")"

echo "${install_script_text}" > installScalyrAgentV2.sh
