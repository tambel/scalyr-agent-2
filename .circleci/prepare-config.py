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

for deployment in deployments.ALL_DEPLOYMENTS.values():
    for step in deployment.steps:
        all_steps[step.unique_name] = step

all_steps = collections.OrderedDict(sorted(all_steps.items(), key=lambda x: x[0]))

restore_cache_steps = []

for step in all_steps.values():
    restore_cache_steps.append({
        "deployment-step": {
            "step-name": step.cache_key,
            "action": "restore-cache"
        }
    })



yaml_step_data = yaml.dump(restore_cache_steps)

yaml_step_data = textwrap.indent(yaml_step_data, "      ")

data = {
    "used_steps": yaml_step_data
}

final_config = template.render(data)



print(final_config)
