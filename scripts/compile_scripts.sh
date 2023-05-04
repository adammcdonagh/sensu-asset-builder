#!/usr/bin/sh -x

# This script will run on the container and is responsible for packaging
# existing python scripts into a compiled executable for that platform/distro

ASSET_NAME=$1
PACKAGES=$2
PACKAGES=`echo ${PACKAGES} | base64 -d`

# For alpine we need gcc etc installed to compile stuff
. /etc/os-release
echo $ID | grep -i alpine >/dev/null && apk add musl-dev libffi gcc linux-headers python3 py3-pip zlib-dev && pip install pyinstaller

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
