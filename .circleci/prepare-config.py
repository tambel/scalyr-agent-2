import collections
import pathlib as pl
import sys
import textwrap
from typing import Dict

import jinja2
import yaml

_PARENT_DIR = pl.Path(__file__).parent.absolute()
_SOURCE_ROOT = _PARENT_DIR.parent

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))


from agent_tools.environment_deployments import deployments
from agent_build import package_builders
from tests.package_tests import current_test_specifications

template_config_path = _PARENT_DIR / "config-template.yml"


template = jinja2.Template(template_config_path.read_text())


all_steps: Dict[str, deployments.DeploymentStep] = {}

deployment_commands = {}

for deployment in deployments.ALL_DEPLOYMENTS.values():

    restore_cache_steps = []
    save_cache_steps = []
    for step in deployment.steps:

        restore_cache_steps.append({
            "restore_cache": {
                "key": f'deployment-steps-cache-{step.cache_key}'
            }
        })

        save_cache_steps.append({
            "save_cache": {
                "key": f'deployment-steps-cache-{step.cache_key}',
                "paths": f"~/deployments-cache/{step.cache_key}"
            }
        })

    deployment_command = {
        "description": "",
        "steps": [
            *restore_cache_steps,
            {
                "run":
                    {
                        f"name": f"Perform deployment: {deployment.name}.",
                        "command": f"python3 scripts/run_deployment.py deployment "
                                   f"{deployment.name} deploy --cache-dir ~/deployments-cache"
                    }
            },
            *save_cache_steps
        ]
    }

    deployment_commands[deployment.name] = deployment_command



yaml_step_data = yaml.dump(deployment_commands)

yaml_step_data = textwrap.indent(yaml_step_data, "  ")

data = {
    "deployments_commands": yaml_step_data
}

final_config = template.render(data)



print(final_config)
