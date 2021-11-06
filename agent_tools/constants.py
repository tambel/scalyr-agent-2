import enum


class DockerPlatform(enum.Enum):
    AMD64 = "amd64"
    ARM64 = "arm64"


class Architecture(enum.Enum):
    X86_64 = "x86_64"
    ARM64 = "arm64"

    @property
    def as_docker_platform(self) -> DockerPlatform:
        global _ARCHITECTURE_TO_DOCKER_PLATFORM
        return _ARCHITECTURE_TO_DOCKER_PLATFORM[self]


_ARCHITECTURE_TO_DOCKER_PLATFORM = {
    Architecture.X86_64: DockerPlatform.AMD64,
    Architecture.ARM64: DockerPlatform.ARM64
}


class PackageType(enum.Enum):
    DEB = "deb"
    RPM = "rpm"
    TAR = "tar"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    K8S = "k8s"
    MSI = "msi"