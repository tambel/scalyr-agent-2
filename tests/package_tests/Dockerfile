ARG BASE_IMAGE_NAME

FROM $BASE_IMAGE_NAME


# Add all files that are involved in the package testing process.
RUN rm -rf /scalyr-agent-2
RUN mkdir /scalyr-agent-2
ADD ./agent_build/environment_deployers /scalyr-agent-2/agent_build/environment_deployers

# Also add the package test module, so the packager also can make the frozen binary for the package tests.
# This frozen binary later can be used to run package tests on systems without python.
ADD ./tests/package_tests/ /scalyr-agent-2/tests/package_tests/

ARG BUILD_COMMAND

# Build the package. Since build options may vary, the build command is prepared outside and is passed there
# though the 'BUILD_COMMAND' argument.
ENV PYTHONPATH="/scalyr-agent-2"
RUN /bin/bash -c "$BUILD_COMMAND"