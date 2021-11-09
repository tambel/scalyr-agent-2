const core = require('@actions/core');
const github = require('@actions/github');
const cache = require('@actions/cache');
const fs = require('fs');
const path = require('path')
const os = require('os')
const child_process = require('child_process')
const buffer = require('buffer')


async function f() {
  try {
    const deploymentName = core.getInput("deployment-name")
    const cacheDir = "deployment_caches"

    const deployment_helper_script_path = path.join(".github", "scripts", "get-deployment.py")
    const code = child_process.execFileSync("python3", [deployment_helper_script_path,"get-deployment-all-cache-names", deploymentName]);

    const json_encoded_deployment_names = buffer.Buffer.from(code, 'utf8').toString()

    const deployer_cache_names = JSON.parse(json_encoded_deployment_names)

    const cache_hits = {}

    for (let name of deployer_cache_names) {

        const cache_path = path.join(cacheDir, name)

        const result = await cache.restoreCache([cache_path], name)

        if(typeof result !== "undefined") {
          console.log(`Cache for the deployment ${name} is found.`)
        } else {
          console.log(`Cache for the deployment ${name} is not found.`)
        }
        cache_hits[name] = result

    }

    child_process.execFileSync(
        "python3",
        [deployment_helper_script_path,"deploy", deploymentName, "--cache-dir", cacheDir],
        {stdio: 'inherit'}
    );

    if ( fs.existsSync(cacheDir)) {
      console.log("Cache directory is found.")

      const filenames = fs.readdirSync(cacheDir);

      for (const name of filenames) {
        const full_child_path = path.join(cacheDir, name)

        if (fs.lstatSync(full_child_path).isDirectory()) {
          if ( ! cache_hits[name] ) {
            console.log(`Save cache for the deployment ${name}.`)
            await cache.saveCache([full_child_path], name)
          } else {
            console.log(`Cache for the deployment ${name} has been hit. Skip saving.`)
          }
        }
      }
    } else {
      console.warn("Cache directory is not found.")
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

f()

