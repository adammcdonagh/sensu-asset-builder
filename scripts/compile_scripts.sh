#!/usr/bin/sh -x

# This script will run on the container and is responsible for packaging
# existing python scripts into a compiled executable for that platform/distro
MY_UID=$1
MY_GID=$2
ASSET_NAME=$3
PACKAGES=$4
PACKAGES=`echo ${PACKAGES} | base64 -d`

# Install any packages required by the python scripts
if [[ ! -z ${PACKAGES} ]]; then
  echo "Installing pip packages ${PACKAGES}"
  pip install ${PACKAGES}
  retval=$?
  if [[ $retval -ne 0 ]]; then
    echo "FAILED downloading PIP packages"
    exit $retval
  fi
fi

# Run pyinstall on all python scripts
cd /src/${ASSET_NAME}
for file in $(ls -1 *.py); do
  pyinstaller --onefile --distpath /build/${ASSET_NAME}/bin/ $file
  retval=$?
  if [[ $retval -ne 0 ]]; then
    echo "FAILED compiling $file"
    exit $retval
  fi
done

# Tidy up src directory
rm -r build *.spec
# Set ownership for all files created to the user that ran the container
chown -R ${MY_UID}:${MY_GID} /build/${ASSET_NAME}
