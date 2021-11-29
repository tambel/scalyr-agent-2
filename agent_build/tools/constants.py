import enum


class DockerPlatform(enum.Enum):
    AMD64 = "linux/amd64"
    ARM64 = "linux/arm64"


class Architecture(enum.Enum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
    NOARCH = "noarch"

    @property
    def as_docker_platform(self) -> DockerPlatform:
        global _ARCHITECTURE_TO_DOCKER_PLATFORM
        return _ARCHITECTURE_TO_DOCKER_PLATFORM[self]


_ARCHITECTURE_TO_DOCKER_PLATFORM = {
    Architecture.X86_64: DockerPlatform.AMD64,
    Architecture.ARM64: DockerPlatform.ARM64,
    # If no architecture specified ,then use x86_64 by default
    Architecture.NOARCH: DockerPlatform.AMD64
}


class PackageType(enum.Enum):
    DEB = "deb"
    RPM = "rpm"
    TAR = "tar"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    K8S = "k8s"
    MSI = "msi"