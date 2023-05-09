#!/bin/env/bash

SCRIPT_COMMAND=$1


# Find all the packages under /var/cache/sensu-agent and add their bin directories to the PATH
ASSET_DIRS=$(find /var/cache/sensu-agent -maxdepth 2 -name bin -type d)
# Add each to the start of the PATH
for dir in $ASSET_DIRS; do
  export PATH=$dir:$PATH
done

# Now run the SCRIPT_COMMAND
$SCRIPT_COMMAND
# Exit with it's returncode
exit $?
