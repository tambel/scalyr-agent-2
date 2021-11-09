const core = require('@actions/core');
const github = require('@actions/github');
const fs = require('fs');

try {
  // `who-to-greet` input defined in action metadata file
  const nameToGreet = core.getInput('who-to-greet');
  const cacheDir = core.getInput('cache-dir');
  console.log(`Hello ${nameToGreet}!`);
  const time = (new Date()).toTimeString();
  core.setOutput("time", time);
  // Get the JSON webhook payload for the event that triggered the workflow
  const payload = JSON.stringify(github.context.payload, undefined, 2)
  console.log(`The event payload: ${payload}`);

  if ( fs.existsSync(cacheDir)) {

    filenames = fs.readdirSync(cacheDir);

    console.log("\nCurrent directory filenames:");
    filenames.forEach(file => {
      console.log(file);
    });
  }

} catch (error) {
  core.setFailed(error.message);
}