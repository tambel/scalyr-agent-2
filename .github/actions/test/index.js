const core = require('@actions/core');
const github = require('@actions/github');
const cache = require('@actions/cache');
const fs = require('fs');
const path = require('path')
const os require('os')



async function f() {
  try {
    // `who-to-greet` input defined in action metadata file
    const nameToGreet = core.getInput('who-to-greet');
    const cacheDir = core.getInput('cache-dir');
    const time = (new Date()).toTimeString();
    // Get the JSON webhook payload for the event that triggered the workflow
    const payload = JSON.stringify(github.context.payload, undefined, 2)

    const fullCachePath = path.join(os.homedir(), cacheDir)
    console.log(fullCachePath)
    if ( fs.existsSync(fullCachePath)) {

      const filenames = fs.readdirSync(fullCachePath);


      console.log("\nCurrent directory filenames:");
      for (const child of filenames) {
        console.log(child);
        if (fs.lstatSync(child).isDirectory()) {
          const key = path.basename(child)
          console.log(key)
          const cacheId = await cache.saveCache(child, key)
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

