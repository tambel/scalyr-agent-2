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

# This script is used by "ShellScriptDeploymentStep"
# (See more in class "ShellScriptDeploymentStep" in the "agent_tools/environment_deployments.py"

# This script install WIX toolset for the Windows MSI builder.

$ProgressPreference = "SilentlyContinue"
$ErrorActionPreference = "Stop"

$cache_path=$args[0]

if ($args[0]) {
    $cache_path=$args[0]
} else {
    $cache_path = "$Env:TEMP\$([System.IO.Path]::GetRandomFileName())"
}

New-Item -ItemType Directory -Force -Path "$cache_path"


$wix_installer_path = "$cache_path\wix311-binaries.zip"
if (!(Test-Path $wix_installer_path -PathType Leaf)) {
    echo "Download WIX toolset."
    wget https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311-binaries.zip -OutFile "$wix_installer_path"
}

$wix_path = "C:\wix311"
Expand-Archive -LiteralPath "$wix_installer_path" -DestinationPath "$wix_path"


$old_path = (Get-ItemProperty -Path 'Registry::HKEY_CURRENT_USER\Environment' -Name path).path

$paths = "$wix_path"
$new_path = "$old_path;$paths"

Set-ItemProperty -Path 'Registry::HKEY_CURRENT_USER\Environment' -Name path -Value $new_path


# Add WIX path to the special paths.txt file. Paths from this file will be added to the PATH variable, so WIX
# toolset will be visible.
$Env:Path = "$Env:Path;$paths"
Add-Content "$cache_path\paths.txt" "$wix_path" -Encoding utf8







