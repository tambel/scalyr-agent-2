import argparse
import os
import re
import subprocess
import sys
import pathlib as pl

from typing import Union

__SOURCE_ROOT__ = pl.Path(__file__).absolute().parent.parent.parent

import tempfile
import time


def build_agent_image(builder_path: pl.Path):
    # build_package_script_path = __SOURCE_ROOT__ / "agent_build/build_package.py"
    #
    # output_path = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2/agent-output-build")
    # subprocess.check_call(
    #     # ["minikube", "start", "-p", "scalyr-agent-test"]
    #     [sys.executable, str(build_package_script_path), "k8s", "build", "--output-dir", str(output_path)]
    # )
    # builder_script_path = list(output_path.glob("k8s/scalyr-k8s-agent-*.*.*"))[0]

    output = subprocess.check_output(
        "minikube docker-env", shell=True
    ).decode()

    env = os.environ.copy()
    for e in re.findall(r'export (\w+=".+")', output):
        (n, v), = re.findall(r'(\w+)="(.+)"', e)
        env[n] = v

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

    scalyr_service_account_manifest_path = __SOURCE_ROOT__ / "k8s" / "scalyr-service-account.yaml"
    try:
        subprocess.check_call(
            "kubectl delete daemonset scalyr-agent-2", shell=True,
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

    subprocess.check_call(
        ["kubectl", "create", "-f", str(scalyr_service_account_manifest_path)]
    )

    # Define API key
    subprocess.check_call(
        ["kubectl", "create", "secret", "generic", "scalyr-api-key", f"--from-literal=scalyr-api-key={scalyr_api_key}"]
    )

    subprocess.check_call(
        [
            "kubectl", "create", "configmap", "scalyr-config",
            "--from-literal=SCALYR_K8S_CLUSTER_NAME=ci-agent-k8s-",
        ]
    )

    scalyr_agent_manifest_source_path = __SOURCE_ROOT__ / "k8s/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        "image: scalyr/scalyr-k8s-agent:k8s_test",
        scalyr_agent_manifest
    )

    scalyr_agent_manifest = re.sub(
        r"imagePullPolicy: \w+", "imagePullPolicy: Never", scalyr_agent_manifest
    )

    tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-k8s-test")

    scalyr_agent_manifest_path = pl.Path(tmp_dir.name) / "scalyr-agent-2.yaml"

    scalyr_agent_manifest_path.write_text(scalyr_agent_manifest)

    subprocess.check_call([
        "kubectl", "create", "-f", str(scalyr_agent_manifest_path)
    ])

    pod_name = subprocess.check_output(
        "kubectl get pods --sort-by=.metadata.creationTimestamp -o jsonpath=\"{.items[-1].metadata.name}\"", shell=True
    ).decode().strip()

    time.sleep(3)

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

    if found_errors:
        print("Errors have been found in the agent log:", file=sys.stderr)
        for line in found_errors:
            print("=====", file=sys.stderr)
            print(line, file=sys.stderr)

        exit(1)

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
