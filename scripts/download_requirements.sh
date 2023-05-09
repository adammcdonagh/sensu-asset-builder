#!/usr/bin/sh -x

# This script will run on the container and is responsible for extracting the python runtime
# and downloading the required python packages into the directory with the asset
MY_UID=$1
MY_GID=$2
ASSET_NAME=$3
PACKAGES=$4

PACKAGES=`echo ${PACKAGES} | base64 -d`

cd /runtime

echo "Installing pip packages ${PACKAGES}"
./bin/python bin/pip install --target /build/${ASSET_NAME}/lib ${PACKAGES}
retval=$?
if [[ $retval -ne 0 ]]; then
  echo "FAILED downloading PIP packages"
  exit $retval
fi

# Set ownership for all files created to the user that ran the container
chown -R ${MY_UID}:${MY_GID} /build/${ASSET_NAME}
