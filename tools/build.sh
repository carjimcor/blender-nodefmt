#!/bin/sh
# Build the extension zip in dist/ and validate it.
#   tools/build.sh            (BLENDER: the Blender executable, default "blender")
set -e
cd "$(dirname "$0")/.."
BLENDER=${BLENDER:-blender}
version=$(sed -n 's/^version = "\(.*\)"/\1/p' nodefmt/blender_manifest.toml)
mkdir -p dist
"$BLENDER" --factory-startup --command extension build --source-dir nodefmt --output-dir dist
"$BLENDER" --factory-startup --command extension validate "dist/nodefmt-$version.zip"
echo "built dist/nodefmt-$version.zip"
