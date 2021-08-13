import argparse
import pathlib as pl
import subprocess
import sys
import time
import datetime
from typing import Union

sys.path.append(str(pl.Path(__file__).absolute().parent.parent.parent))

from tests.package_tests.common import PipeReader, check_agent_log_request_stats_in_line, check_if_line_an_error
from tests.package_tests.common import COMMON_TIMEOUT


def build_agent_image(builder_path: pl.Path):
    # Call the image builder script.
    subprocess.check_call(
        [str(builder_path), "--tags", "docker-test"],
    )


_AGENT_CONTAINER_NAME = "scalyr-agent-docker-test"


def _delete_agent_container():

    # Kill and remove the previous container, if exists.
    subprocess.check_call(
        ["docker", "rm", "-f", _AGENT_CONTAINER_NAME]
    )


def _test(scalyr_api_key: str):

    # Run agent inside the container.
    subprocess.check_call(
        [
            "docker", "run", "-d", "--name", _AGENT_CONTAINER_NAME, "-e", f"SCALYR_API_KEY={scalyr_api_key}",
            "-v", "/var/run/docker.sock:/var/scalyr/docker.sock", "scalyr/scalyr-agent-docker-json:docker-test"
        ]
    )

    # Wait a little.
    time.sleep(3)

    # Execute tail -f command on the agent.log inside the container to read its content.
    agent_log_tail_process = subprocess.Popen(
        ["docker", "exec", "-i", _AGENT_CONTAINER_NAME, "tail", "-f", "-n+1", "/var/log/scalyr-agent-2/agent.log"],
        stdout=subprocess.PIPE
    )

    # Read lines from agent.log.
    pipe_reader = PipeReader(pipe=agent_log_tail_process.stdout)

    timeout_time = datetime.datetime.now() + datetime.timedelta(seconds=COMMON_TIMEOUT)
    try:
        while True:

            seconds_until_timeout = timeout_time - datetime.datetime.now()
            line = pipe_reader.next_line(timeout=seconds_until_timeout.seconds)
            print(line)
            # Look for any ERROR message.
            check_if_line_an_error(line)

            # TODO: add more checks.

            if check_agent_log_request_stats_in_line(line):
                # The requests status message is found. Stop the loop.
                break
    finally:
        agent_log_tail_process.terminate()

    agent_log_tail_process.communicate()

    print("Test passed!")


def main(
    builder_path: Union[str, pl.Path],
    scalyr_api_key: str
):

    build_agent_image(builder_path)
    _delete_agent_container()

    try:
        _test(scalyr_api_key)
    finally:
        _delete_agent_container()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--builder-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    main(
        builder_path=args.builder_path,
        scalyr_api_key=args.scalyr_api_key
    )