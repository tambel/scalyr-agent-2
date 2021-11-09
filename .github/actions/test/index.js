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
    // `who-to-greet` input defined in action metadata file
    const nameToGreet = core.getInput('who-to-greet');
    const cacheDir = "deployment_caches"
    const time = (new Date()).toTimeString();
    // Get the JSON webhook payload for the event that triggered the workflow
    const payload = JSON.stringify(github.context.payload, undefined, 2)

    const deployment_helper_script_path = path.join(".github", "scripts", "get-deployment.py")
    const code = child_process.execFileSync("python3", [deployment_helper_script_path,"get-deployment-all-cache-names", "base_environment_windows_agent_builder_x86_64"]);

    const json_encoded_deployment_names = buffer.Buffer.from(code, 'utf8').toString()


    const deployer_cache_names = JSON.parse(json_encoded_deployment_names)

    console.log(deployer_cache_names)

    for (let item of deployer_cache_names) {
        console.log(item);
    }

    // deployer_cache_names.x(function(value){
    //   console.log(value);
    // });

    // deployer_cache_names.forEach(obj => {
    //     Object.entries(obj).forEach(([key, value]) => {
    //         console.log(`${key} ${value}`);
    //     });
    //     console.log('-------------------');
    // });

    for (const deployer_cache_name in deployer_cache_names) {

    }

    //console.log()
    console.log("11111111")
    console.log(cacheDir)
    if ( fs.existsSync(cacheDir)) {

      const filenames = fs.readdirSync(cacheDir);


      console.log("\nCurrent directory filenames:");
      for (const child of filenames) {
        const full_child_path = path.join(cacheDir, child)
        console.log(full_child_path);

        if (fs.lstatSync(full_child_path).isDirectory()) {
          const key = path.basename(child)
          console.log(key)
          //const cacheId = await cache.saveCache([full_child_path], key)
          //cache.restoreCache([full_child_path],)
        }
      }
    } else {
      console.log("NOTEXIST")
    }
    core.setOutput("time", time);
    console.log(`Hello ${nameToGreet}!`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

f()

