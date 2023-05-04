#!/usr/bin/env python

import argparse
import base64
import glob
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sys

import pygit2
import requests
import yaml
from ghapi.all import GhApi
from jsmin import jsmin

SCRIPT_VERSION = "1.0"

# Change history:
# v1.0 - Initial version
#

# This script is responsible for building asset packages and generating the SHA512 sum, and a templated
# yml file for importing into Sensu
# The output can then be uploaded to a "bonsai" repo ready for Sensu to pull down
TMP_DIR = "/tmp/sensu-asset-builder"
BONSAI_PROTOCOL = os.getenv("BONSAI_PROTOCOL")
BONSAI_HOST = os.getenv("BONSAI_HOST")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PYTHON_RUNTIME_REPO = os.getenv("PYTHON_RUNTIME_REPO")
BUF_SIZE = 65536


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="verbose mode", action="store_true")
    parser.add_argument(
        "-c",
        "--config",
        help="config file",
        required=False,
        default="assets.json",
    )
    parser.add_argument("-a", "--asset", help="build a specific asset", required=False)
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    start_dir = f"{os.path.dirname(os.path.abspath(__file__))}"
    build_dir = f"{start_dir}/../build"
    assets_dir = f"{start_dir}/../assets"

    # Make sure the TMP_DIR is empty
    shutil.rmtree(TMP_DIR, ignore_errors=True)

    this_os = platform.uname().system
    architecture = platform.uname().machine
    logging.debug(f"Local architecture is {architecture}")

    # if not BONSAI_PROTOCOL:
    #     logging.error("No BONSAI_PROTOCOL specified in environment")
    #     return 1

    # if not BONSAI_HOST:
    #     logging.error("No BONSAI_HOST specified in environment")
    #     return 1

    # Check that the github cli is installed, if a GITHUB_TOKEN is not set
    if not os.environ.get("GITHUB_TOKEN") and not shutil.which("gh"):
        logging.error("Github CLI is not installed")
        return 1

    if not os.environ.get("GITHUB_TOKEN"):
        # Use the github cli to pull the token to use to API calls
        os.environ["GITHUB_TOKEN"] = os.popen("gh auth token").read().strip()

    gh = GhApi(authenticate=True, token=os.environ.get("GITHUB_TOKEN"))

    # Handle MacOS M1
    if this_os == "macOS" and architecture == "arm64":
        architecture = "aarch64"

    # Open the config file and parse it
    asset_config = None
    try:
        with open(args.config) as json_file:
            json_data = jsmin(json_file.read())
            asset_config = json.loads(json_data)
    except FileNotFoundError:
        logging.error(f"Failed to open {args.config}")
        return 1

    # Store a list of repos we need to clone, rather than duplicate effort if
    # multiple assets require the same repo
    required_repos = []

    # Loop through each asset in the config and determine which assets need building
    for asset in asset_config["assets"]:
        # If we are building a specific asset, skip all others
        if args.asset and not args.asset == asset["name"]:
            # Remove it from the config so we don't have to check again
            asset_config["assets"].remove(asset)
            continue

        logging.info(f"{BColours.HEADER}Processing {asset['name']}{BColours.ENDC}")

        # Store the repo path for this asset
        repo = asset["source_repo"]
        if repo not in required_repos:
            required_repos.append(repo)

    # Loop through each repo and clone it
    for repo in required_repos:
        logging.info(f"Cloning {repo}")
        # Clone the repo into the TMP_DIR
        os.system(f"gh repo clone {repo} {TMP_DIR}/{repo.split('/')[-1]}")

    # Create a requests Session object
    session = requests.Session()
    session.headers = {
        "Authorization": f"token {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Loop through the assets again, now that they've been downloaded locally
    for asset in asset_config["assets"]:
        asset_name = asset["name"]
        logging.info(f"{BColours.OKCYAN}Processing asset {asset_name}{BColours.ENDC}")
        asset_root_dir = f"{TMP_DIR}/{asset['source_repo'].split('/')[-1]}/{asset['source_repo_root_dir']}/{asset_name}"

        # Open the asset_metadata.json file and open it
        asset_metadata = None
        try:
            with open(f"{asset_root_dir}/asset_metadata.json") as json_file:
                json_data = jsmin(json_file.read())
                asset_metadata = json.loads(json_data)

        except FileNotFoundError:
            logging.error(
                f"{BColours.FAIL}Failed to find an asset_metadata.json for {asset_root_dir} asset{BColours.ENDC}"
            )
            return 1

        asset_sensu_name = asset_metadata["asset_name"]
        asset_version = asset_metadata["version"]
        requirements = asset_metadata["requirements"]
        python_version = asset_metadata["python_version"]

        for system in asset_metadata["systems"]:
            logging.info(f"Processing build for {system}")
            # Create the structure for the asset based on the build_structure template directory
            shutil.rmtree(f"{build_dir}/{asset_name}", ignore_errors=True)
            shutil.copytree(
                f"{start_dir}/build_structure",
                f"{build_dir}/{asset_name}",
                symlinks=True,
            )

            # Copy the contents of the asset directory into the libexec for the build directory
            shutil.copytree(
                f"{asset_root_dir}/",
                f"{build_dir}/{asset_name}/libexec/",
                dirs_exist_ok=True,
            )

            # Create a symlink in bin for each asset .py file pointing to the wrapper in share directory
            asset_files = glob.glob(f"{build_dir}/{asset_name}/libexec/*.py")
            for asset_file in asset_files:
                script_name = os.path.basename(asset_file)
                os.symlink(
                    "../share/wrapper", f"{build_dir}/{asset_name}/bin/{script_name}"
                )

            # If arch is not specified, build it for whatever the machine doing the build is running
            if "arch" not in system:
                # If the local machine is an Apple ARM chip, then use that architecture
                if architecture == "aarch64":
                    system["arch"] = "aarch64"
                # Otherwise default to x64
                else:
                    system["arch"] = "amd64"

            # Skip aarch64 builds on non M1 machines - Since you can't do an M1 build on anything that's not a Mac
            # And these are just used for testing locally anyway, so there's no need for the build process to run M1 builds
            if system["arch"] == "aarch64" and architecture != "aarch64":
                logging.info("Skipping build for aarch64 on non M1 architecture")
                continue

            asset_file_platform_family = (
                system["platform_family"] if "platform_family" in system else ""
            )

            platform_family = (
                system["platform_family"] if "platform_family" in system else ""
            )
            platform_version = (
                system["platform_version"] if "platform_version" in system else ""
            )

            if platform_family == "rhel" and platform_version and platform_version == 7:
                docker_image = "centos:7"
                asset_file_platform_family = "rhel7"
            elif platform_family == "rhel":
                docker_image = "almalinux"
                asset_file_platform_family = "rhel8"

            # Now the structure is in place, see if there are any requirements to install
            if (
                True
                or requirements
                or ("is_compiled" in asset_metadata and asset_metadata["is_compiled"])
            ):
                # We need to loop through each platform, use the python runtime assets as a runtime to
                # trigger pip to download the assets we need. Package them up and place them under the lib directory
                # of this asset

                # Download assets linked to the python runtime repo
                # Use the gh CLI to list the assets for the latest release
                if not PYTHON_RUNTIME_REPO:
                    logging.error(
                        "PYTHON_RUNTIME_REPO is not defined in the environment"
                    )
                    return 1
                runtime_repo_owner = PYTHON_RUNTIME_REPO.split("/")[0]
                runtime_repo_name = PYTHON_RUNTIME_REPO.split("/")[1]

                response = session.get(
                    f"https://api.github.com/repos/{runtime_repo_owner}/{runtime_repo_name}/releases"
                )
                if response.status_code != 200:
                    logging.error(
                        "Error returned from GitHub when trying to obtain Python runtime"
                    )
                    return 1

                response_json = json.loads(response.content)

                # sensu-python-runtime_local-build_python-3.9.10_vanilla-alpine_linux_x86_64.tar.gz
                obtained_runtime = False
                for release in response_json:
                    # convert platform_family into short name used in files
                    this_platform = None
                    if platform_family == "rhel":
                        this_platform = f"rhel{system['platform_version']}"
                    elif platform_family == "amazonlinux":
                        this_platform = "amzn2"
                    elif platform_family == "alpine":
                        this_platform = "alpine"

                    for release_asset in release["assets"]:
                        ## Pull the release_asset with requests, so we have SSL support (so pip works)
                        # TEMP:  Try getting the vanilla release first (just to see if it works)
                        arch = system["arch"]
                        if arch == "amd64":
                            arch = "x86_64"
                        regex = f"sensu-python-runtime.*python-{python_version}_vanilla-{this_platform}_linux_{arch}"

                        # sensu-python-runtime_v1.1_python-3.9.10_vanilla-alpine_linux_aarch64.tar.gz
                        if re.search(regex, release_asset["name"]):
                            logging.info(
                                f"{BColours.OKGREEN}Found vanilla build for Python {python_version}{BColours.ENDC}"
                            )
                            # Check if the file already exists locally
                            python_runtime_path = f"{build_dir}/{release_asset['name']}"
                            # Update the json object with the name of the file we have downloaded
                            system["runtime_file"] = release_asset["name"]

                            # Check if it exists and isnt 0 size
                            if (
                                os.path.exists(python_runtime_path)
                                and os.path.getsize(python_runtime_path) > 0
                            ):
                                logging.info("Already have a copy of the runtime")
                                obtained_runtime = True
                                continue

                            # Download the runtime locally
                            with open(python_runtime_path, "wb") as file:
                                logging.info(f"Downloading {release_asset['url']}")
                                response = session.get(
                                    release_asset["url"],
                                    headers={"Accept": "application/octet-stream"},
                                )
                                file.write(response.content)
                                obtained_runtime = True

                if not obtained_runtime:
                    logging.error(
                        f"{BColours.FAIL}Unable to obtain Python runtime for {python_version}{BColours.ENDC}"
                    )
                    sys.exit(1)

                # At this point we've got a file for each platform that we should need
                # Now we need to spin up a container for each system and download the pip package that we want
                # Get the name of the container that we need from the platform name

                logging.info(
                    f"Getting packages for {platform_family}:{platform_version}"
                )

                docker_platform = ""
                if system["arch"] != architecture:
                    docker_platform = f"--platform linux/{system['arch']}"

                # for M1, if we've been using x86 platforms, we need to specify to use the ARM platform if that's what we are
                # building for so that the right image actually gets used, otherwise it might use an x86 image that was previously
                # downloaded
                if architecture == "aarch64" and system["arch"] == "aarch64":
                    docker_platform = "--platform linux/arm64/v8"

                # Set the docker image if this is rhel
                docker_image = platform_family

                # Determine the runtime dir
                runtime_dir = (
                    f"{build_dir}/runtimes/{asset_file_platform_family}-{arch}"
                )

                # Extract the tar (if bin/python doesnt already exist), into the runtime_dir
                if not os.path.exists(f"{runtime_dir}/bin/python"):
                    os.system(
                        f"mkdir -p {runtime_dir} 2>/dev/null; cd {runtime_dir} && tar xf {build_dir}/{system['runtime_file']}"
                    )

                # This is where we either download the requirements, or compile the script into a binary
                # Base64 encode the package list
                packages = base64.b64encode(
                    " ".join(requirements).encode("ascii")
                ).decode("ascii")
                if requirements and (
                    "is_compiled" not in asset_metadata
                    or not asset_metadata["is_compiled"]
                ):
                    docker_command = f"docker run {docker_platform} --rm -v {build_dir}:/build -v {start_dir}:/src -v {runtime_dir}:/runtime {docker_image} sh /src/download_requirements.sh /build/{system['runtime_file']} {asset_name} {packages}"
                    logging.info(f"Running: {docker_command}")
                    rc = os.system(docker_command)
                    if rc != 0:
                        logging.error(
                            f"{BColours.FAIL}Bundle of package for {platform_family} failed{BColours.ENDC}"
                        )
                        return 1
                else:
                    # Compile the scripts into a binary
                    docker_command = f"docker run {docker_platform} --rm -v {build_dir}:/build -v {start_dir}:/src -v {runtime_dir}:/runtime {docker_image} sh /src/compile_scripts.sh {asset_name} {packages}"
                    logging.info(f"Running: {docker_command}")
                    rc = os.system(docker_command)
                    if rc != 0:
                        logging.error(
                            f"{BColours.FAIL}Compile of scripts for {platform_family} failed{BColours.ENDC}"
                        )
                        return 1

            # Second last step is to tar the asset and generate the sha512 sum for it
            asset_output_file = f"{assets_dir}/{asset_name}_{asset_version}_{asset_file_platform_family + '_' if asset_file_platform_family else ''}{system['os']}_{system['arch']}.tar.gz"
            tar_command = f"tar czf {asset_output_file} -C {build_dir}/{asset_name} ./"
            rc = os.system(tar_command)

            if rc != 0:
                logging.error(f"{BColours.FAIL}Tar of assets failed{BColours.ENDC}")
                return 1

            # Generate the sha512 sum
            sha512 = hashlib.sha512()
            with open(asset_output_file, "rb") as f:
                while True:
                    data = f.read(BUF_SIZE)
                    if not data:
                        break
                    sha512.update(data)

            print(f"SHA512: {sha512.hexdigest()}")
            # Update the object with the asset name and sha512 sum
            system["asset_output_file"] = asset_output_file
            system["sha512sum"] = sha512.hexdigest()

        # Create the asset YML file
        asset_yml = dict()
        asset_yml["type"] = "Asset"
        asset_yml["api_version"] = "core/v2"
        asset_yml["metadata"] = dict()
        asset_yml["metadata"]["name"] = f"{asset_name}_v{asset_version}"

        asset_yml["spec"] = dict()
        asset_yml["spec"]["builds"] = []

        # Create the builds array
        for system in asset_metadata["systems"]:
            # Check that we had a successful build, otherwise skip it (maybe it was for M1 or something)
            if "sha512sum" not in system:
                continue
            system_specific_asset_definition = {
                "sha512": system["sha512sum"],
                "url": f"{BONSAI_PROTOCOL}://{BONSAI_HOST}/{os.path.basename(system['asset_output_file'])}",
            }

            filters = []

            # Add the conditions
            for filter in system["sensu_filters"]:
                filters.append(filter)

            system_specific_asset_definition["filters"] = filters

            asset_yml["spec"]["builds"].append(system_specific_asset_definition)

        # Write the asset yml along with the asset
        asset_build_dir = f"{build_dir}/{asset_name}"
        if not os.path.exists(asset_build_dir):
            os.makedirs(asset_build_dir)

        with open(f"{asset_build_dir}/asset.yml", "w") as yml_file:
            yaml.dump(
                asset_yml,
                yml_file,
                default_flow_style=False,
                sort_keys=False,
                explicit_start=True,
            )
            logging.info(
                yaml.dump(
                    asset_yml,
                    default_flow_style=False,
                    sort_keys=False,
                    explicit_start=True,
                )
            )

        # Tidy up the build dir
        shutil.rmtree(f"{build_dir}/{asset_name}", ignore_errors=True)
        logging.info(
            f"{BColours.OKGREEN}Successfully built asset: {asset_name}{BColours.ENDC}"
        )

    return 0


class BColours:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
rc = main()
# Tidy up the temporary directory
shutil.rmtree(TMP_DIR, ignore_errors=True)

sys.exit(rc)
