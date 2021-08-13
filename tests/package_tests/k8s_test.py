import argparse
import datetime
import os
import queue
import re
import subprocess
import sys
import pathlib as pl
import threading

from typing import Union, IO

__SOURCE_ROOT__ = pl.Path(__file__).absolute().parent.parent.parent

import tempfile
import time

# Timeout 5 minutes.
TIMEOUT = 2 * 60


class PipeReader:
    """
    Simple reader to read process pipes. Since it's not possible to perform a non-blocking read from pipe,
    we just read it in a separate thread and put it to the queue.
    """
    def __init__(self, pipe: IO):
        self._pipe = pipe
        self._queue = queue.Queue()
        self._started = False
        self._thread = None

    def read_pipe(self):
        """
        Reads lines from pipe. Runs in a separate thread.
        """
        while True:
            line = self._pipe.readline()
            if line == b'':
                break
            self._queue.put(line.decode())

    def next_line(self, timeout: int):
        """
        Return lines from queue if presented.
        """
        if not self._thread:
            self._thread = threading.Thread(target=self.read_pipe)
            self._thread.start()
        return self._queue.get(timeout=timeout)






def build_agent_image(builder_path: pl.Path):
    # Get the information about minikube's docker environment.
    output = subprocess.check_output(
        "minikube docker-env", shell=True
    ).decode()

    # Parse environment variables from the 'minikube docker-env' output
    env = os.environ.copy()
    for e in re.findall(r'export (\w+=".+")', output):
        (n, v), = re.findall(r'(\w+)="(.+)"', e)
        env[n] = v

    # Call the image builder script. We also pass previously parsed docker-env variables to build this image
    # within the minikube's docker, so the result agent's image is available for kubernetes.
    subprocess.check_call(
        [str(builder_path), "--tags", "k8s_test"],
        env=env
    )


def main(
        builder_path: Union[str, pl.Path],
        scalyr_api_key: str
):

    builder_path = pl.Path(builder_path)

    build_agent_image(builder_path)

    # Delete previously created objects, if presented.
    scalyr_service_account_manifest_path = __SOURCE_ROOT__ / "k8s" / "scalyr-service-account.yaml"
    try:
        subprocess.check_call(
            "kubectl delete daemonset scalyr-agent-2", shell=True
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete secret scalyr-api-key", shell=True,
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete configmap scalyr-config", shell=True,
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            ["kubectl", "delete", "-f", str(scalyr_service_account_manifest_path)],
        )
    except subprocess.CalledProcessError:
        pass

    # Create agent's service account.
    subprocess.check_call(
        ["kubectl", "create", "-f", str(scalyr_service_account_manifest_path)]
    )

    # Define API key
    subprocess.check_call(
        ["kubectl", "create", "secret", "generic", "scalyr-api-key", f"--from-literal=scalyr-api-key={scalyr_api_key}"]
    )

    # Create configmap
    subprocess.check_call(
        [
            "kubectl", "create", "configmap", "scalyr-config",
            "--from-literal=SCALYR_K8S_CLUSTER_NAME=ci-agent-k8s-",
        ]
    )

    # Modify the manifest for the agent's daemonset.
    scalyr_agent_manifest_source_path = __SOURCE_ROOT__ / "k8s/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    # Change the production image name to the local one.
    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        "image: scalyr/scalyr-k8s-agent:k8s_test",
        scalyr_agent_manifest
    )

    # Change image pull policy to be able to bull the local image.
    scalyr_agent_manifest = re.sub(
        r"imagePullPolicy: \w+", "imagePullPolicy: Never", scalyr_agent_manifest
    )

    # Create new manifest file for the agent daemonset.
    tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-k8s-test")

    scalyr_agent_manifest_path = pl.Path(tmp_dir.name) / "scalyr-agent-2.yaml"

    scalyr_agent_manifest_path.write_text(scalyr_agent_manifest)

    # Create agent's daemonset.
    subprocess.check_call([
        "kubectl", "create", "-f", str(scalyr_agent_manifest_path)
    ])

    # Get name of the created pod.
    pod_name = subprocess.check_output(
        "kubectl get pods --sort-by=.metadata.creationTimestamp -o jsonpath=\"{.items[-1].metadata.name}\"", shell=True
    ).decode().strip()

    # Wait a little.
    time.sleep(3)

    # Execute tail -f command on the agent.log inside the pod to read its content.
    agent_log_tail_process = subprocess.Popen(
        ["kubectl", "exec", pod_name, "--container", "scalyr-agent", "--", "tail", "-f", "-n+1", "/var/log/scalyr-agent-2/agent.log"],
        stdout=subprocess.PIPE
    )
    found_errors = []

    agent_log_line_timestamp = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z"

    # The pattern to match the periodic message lines with network request statistics. This message is written only when
    # all startup messages are written, so it's a good time to stop the verification of the agent.log file.
    requests_pattern = rf"{agent_log_line_timestamp} INFO \[core] \[scalyr-agent-2:\d+] " \
                       r"agent_requests requests_sent=(?P<requests_sent>\d+) " \
                       r"requests_failed=(?P<requests_failed>\d+) " \
                       r"bytes_sent=(?P<bytes_sent>\d+) " \
                       r".+"

    failed = False

    timeout_time = datetime.datetime.now()
    reader = PipeReader(agent_log_tail_process.stdout)

    try:
        while True:

            seconds_until_timeout = timeout_time - datetime.datetime.now()
            line = reader.next_line(timeout=seconds_until_timeout.seconds)

            # Look for any ERROR message.
            if re.match(rf"{agent_log_line_timestamp} ERROR .*", line):
                found_errors.append(line)

            # Match for the requests status message.
            m = re.match(requests_pattern, line)

            if m:
                # The requests status message is found. Stop the loop.
                # But also do a final check for a valid request stats.
                md = m.groupdict()
                requests_sent = int(md["requests_sent"])
                bytes_sent = int(md["bytes_sent"])
                if bytes_sent <= 0 and requests_sent <= 0:
                    print("Agent log says that during the run the agent sent zero bytes or requests.", file=sys.stderr)
                    failed = True
                break
    except Exception as e:
        print(e, file=sys.stderr)
        failed = True
    finally:
        agent_log_tail_process.terminate()

    if found_errors:
        print("Errors have been found in the agent log:", file=sys.stderr)
        for line in found_errors:
            print("=====", file=sys.stderr)
            print(line, file=sys.stderr)

        failed = True

    if failed:
        print("Test failed.", file=sys.stderr)
        exit(1)

    print("Test passed!")

    return

    #
    agent_status = subprocess.check_output(
        ["kubectl", "exec", pod_name, "--container", "scalyr-agent", "--", "scalyr-agent-2", "status", "-v"]
    ).decode()

    print("Agent status:")
    print(agent_status)

    logs_dir = pl.Path(tmp_dir.name) / "agent_logs"
    logs_dir.mkdir()

    # copy agent logs from the pod.
    subprocess.check_call(
        ["kubectl", "cp", f"{pod_name}:/var/log/scalyr-agent-2", str(logs_dir)]
    )

    agent_log_path = logs_dir / "agent.log"

    agent_log_text = agent_log_path.read_text()
    # Do a simple check for any error lines in the agent log file.
    found_errors = re.findall(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z ERROR .*$",
        agent_log_text,
        flags=re.MULTILINE
    )

    # TODO: Add more checks.

    tmp_dir.cleanup()



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--builder-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    main(
        builder_path=args.builder_path,
        scalyr_api_key=args.scalyr_api_key
    )
