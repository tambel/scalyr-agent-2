import enum

from .utils import *

class InstallType(enum.Enum):
    """
    The enumeration of the Scalyr agent installation types. It is used for INSTALL_TYPE variable in the scalyr_agent
    module.
    """

    # Those package types contain Scalyr Agent as frozen binary.
    PACKAGE_INSTALL = "package"  # Indicates it was installed via a package manager such as RPM or Windows executable.
    SOURCE_PACKAGE = "source_package"
    TARBALL_INSTALL = "packageless"  # Indicates it was installed via a tarball.

    # This type runs Scalyr Agent from the source code.
    DEV_INSTALL = "dev"  # Indicates source code is running out of the original source tree, usually during dev testing.