const core = require('@actions/core');
const github = require('@actions/github');
const cache = require('@actions/cache');
const fs = require('fs');
const path = require('path')
const os = require('os')



async function f() {
  try {
    // `who-to-greet` input defined in action metadata file
    const nameToGreet = core.getInput('who-to-greet');
    const cacheDir = core.getInput('cache-dir');
    const time = (new Date()).toTimeString();
    // Get the JSON webhook payload for the event that triggered the workflow
    const payload = JSON.stringify(github.context.payload, undefined, 2)

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
          const cacheId = await cache.saveCache([full_child_path], key)
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

