# Sensu Asset Builder

This repo is designed to be used to create packaged Sensu assets. It is provided with a JSON file (`assets.json`) containing the details of the assets to package, as well as the intended destination to store them afterwards (assumed to be an S3 bucket)

## assets.json

Here's an example of the `assets.json`. It contains an array of assets to be packaged, along with the destination to upload the assets to afterwards.

```json
{
  "assets": [
    {
      "name": "linux_os_metrics",
      "type": "python",
      "source_repo": "github.com/adammcdonagh/sensu-assets",
      "source_repo_root_dir": "src/python"
    }
  ],
  "destination": {
    "type": "s3",
    "bucket_name": "my-s3-bucket",
    "bucket_path": ""
  }
}
```

## Running manually

Use the `build.py` script to run the build and package process. If required, you can override the default asset list JSON file using the `--asset_list <json file>` argument. 

## Testing

The `test` directory contains a set of scripts that use Docker and [localstack](https://localstack.cloud/) to spin up a Sensu test environment to validate that the packaged assets all work. Each asset should contain in it's metadata definition, a test command which can be used to validate the basic functionallity of the script itself. The Sensu environment will be configured to run each check every 60 seconds, using the test command against each asset.

The Sensu `sensu/sensu:latest` docker image is used to spin up the server and client, since it's the simplest way to automate. This means that only the Alpine build of each asset will actually be fully tested.

## Automating

This repo contains a fully populated `assets.json` file, and also a GitHub Actions workflow that is used to run the full build/test/deploy process when PRs are raised/merged into main. If running outside of GitHub Actions, this can simply be converted into shell commands and run elsewhere.
