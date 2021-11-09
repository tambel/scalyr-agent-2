const core = require('@actions/core');
const github = require('@actions/github');
const cache = require('@actions/cache');
const fs = require('fs');
const path = require('path')
const os = require('os')
const child_process = require('child_process')
const buffer = require('buffer')
const readline = require('readline')


async function f() {
  try {
    const deploymentName = core.getInput("deployment-name")
    const cacheVersionSuffix = core.getInput("cache-version-suffix")
    const cacheDir = "deployment_caches"

    const deployment_helper_script_path = path.join(".github", "scripts", "get-deployment.py")
    const code = child_process.execFileSync("python3", [deployment_helper_script_path,"get-deployment-all-cache-names", deploymentName]);

    const json_encoded_deployment_names = buffer.Buffer.from(code, 'utf8').toString()

    const deployer_cache_names = JSON.parse(json_encoded_deployment_names)

    const cache_hits = {}

    for (let name of deployer_cache_names) {

        const cache_path = path.join(cacheDir, name)

        const key = `${name}-${cacheVersionSuffix}`

        const result = await cache.restoreCache([cache_path], key)

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

          const key = `${name}-${cacheVersionSuffix}`

          if ( ! cache_hits[name] ) {
            console.log(`Save cache for the deployment ${name}.`)
            await cache.saveCache([full_child_path], key)
          } else {
            console.log(`Cache for the deployment ${name} has been hit. Skip saving.`)
          }
          const paths_file_path = path.join(full_child_path, "paths.txt")
          if (fs.existsSync(paths_file_path)) {

            var lineReader = readline.createInterface({
              input: fs.createReadStream(paths_file_path)
            });

            lineReader.on('line', function (line) {
              console.log('Line from file:', line);
              core.addPath(line)
            });
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

