#!/usr/bin/sh -x

# This script will run on the container and is responsible for extracting the python runtime
# and downloading the required python packages into the directory with the asset

RUNTIME_PACKAGE=$1
ASSET_NAME=$2
PACKAGES=$3

PACKAGES=`echo ${PACKAGES} | base64 -d`

cd /runtime
# # Extract the runtime if it hasn't already been done
# if [[ ! -e "./bin/python" ]]; then
#   . /etc/os-release
#   # Ensure tar is installed
#   echo $ID_LIKE | grep rhel >/dev/null && (tar --help >/dev/null 2>&1 || (echo "Installing tar and gzip" && update-ca-trust && yum install -y tar gzip >/dev/null))

#   echo "Extracting Python runtime"
#   tar xf $RUNTIME_PACKAGE
#   retval=$?
#   if [[ $retval -ne 0 ]]; then
#     echo "FAILED extracting package"
#     exit $retval
#   fi
# fi

# For alpine we need gcc etc installed to compile stuff
. /etc/os-release
echo $ID | grep -i alpine >/dev/null && apk add musl-dev libffi gcc linux-headers

echo "Installing pip packages ${PACKAGES}"
./bin/python bin/pip install --target /build/${ASSET_NAME}/lib ${PACKAGES}
retval=$?
if [[ $retval -ne 0 ]]; then
  echo "FAILED downloading PIP packages"
  exit $retval
fi
