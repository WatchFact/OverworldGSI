#!/usr/bin/env bash
# Build a real, source-compiled AOSP Generic System Image.
set -Eeuo pipefail

AOSP_BRANCH="${AOSP_BRANCH:-android17-release}"
AOSP_TARGET="${AOSP_TARGET:-gsi_arm64-userdebug}"
AOSP_WORKDIR="${AOSP_WORKDIR:-$PWD/aosp-workdir}"
DIST_DIR="${DIST_DIR:-$PWD/dist}"
SYNC_JOBS="${SYNC_JOBS:-4}"
BUILD_JOBS="${BUILD_JOBS:-4}"

if [[ ! "$AOSP_BRANCH" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
  echo "::error::Invalid AOSP branch" >&2; exit 2
fi
case "$AOSP_TARGET" in
  gsi_arm-user|gsi_arm-userdebug|gsi_arm64-user|gsi_arm64-userdebug|\
  gsi_x86-user|gsi_x86-userdebug|gsi_x86_64-user|gsi_x86_64-userdebug) ;;
  *) echo "::error::Unsupported GSI target: $AOSP_TARGET" >&2; exit 2 ;;
esac

for command in repo git python3 xz sha256sum df; do
  command -v "$command" >/dev/null || {
    echo "::error::Missing required command: $command" >&2; exit 1;
  }
done
[[ "$(uname -s)" == "Linux" ]] || {
  echo "::error::AOSP source builds require Linux" >&2; exit 1;
}
[[ "$(uname -m)" == "x86_64" ]] || {
  echo "::error::AOSP host tools require an x86_64 build host" >&2; exit 1;
}

mkdir -p "$AOSP_WORKDIR" "$DIST_DIR"
AOSP_WORKDIR="$(cd "$AOSP_WORKDIR" && pwd -P)"
DIST_DIR="$(cd "$DIST_DIR" && pwd -P)"
free_kib="$(df -Pk "$AOSP_WORKDIR" | awk 'END { print $4 }')"
free_gib=$((free_kib / 1024 / 1024))
# AOSP documents 400 GB of space for a fresh checkout + build.
if [[ ! -d "$AOSP_WORKDIR/.repo" && "$free_gib" -lt 400 ]]; then
  echo "::error::Full AOSP source checkout needs about 400 GiB free; found ${free_gib} GiB. Use a larger/self-hosted runner." >&2
  exit 1
fi

cd "$AOSP_WORKDIR"
echo "::group::Sync official AOSP: $AOSP_BRANCH"
repo init --partial-clone \
  -u https://android.googlesource.com/platform/manifest \
  -b "$AOSP_BRANCH"
repo sync -c --no-tags --optimized-fetch --prune -j "$SYNC_JOBS"
echo "::endgroup::"

echo "::group::Build $AOSP_TARGET"
# shellcheck disable=SC1091
source build/envsetup.sh
lunch "$AOSP_TARGET"
product_out="$(get_build_var PRODUCT_OUT)"
[[ -n "$product_out" ]] || { echo "::error::PRODUCT_OUT missing"; exit 1; }
m -j "$BUILD_JOBS" systemimage
echo "::endgroup::"

system_image="$product_out/system.img"
if [[ ! -s "$system_image" ]]; then
  echo "::error::No system.img was produced by AOSP" >&2
  exit 1
fi
filename="OverworldGSI-${AOSP_BRANCH}-${AOSP_TARGET}-system.img"
cp --sparse=always "$system_image" "$DIST_DIR/$filename"
(cd "$DIST_DIR" && sha256sum "$filename" > "$filename.sha256")
xz -T "$BUILD_JOBS" -6 -k "$DIST_DIR/$filename"
(cd "$DIST_DIR" && sha256sum "$filename.xz" > "$filename.xz.sha256")
repo manifest -r -o "$DIST_DIR/source-manifest.xml"
python3 - "$DIST_DIR" "$filename" "$AOSP_BRANCH" "$AOSP_TARGET" <<'PY'
import hashlib
import json
import pathlib
import sys

dist = pathlib.Path(sys.argv[1])
filename, branch, target = sys.argv[2:]
image = dist / filename
with image.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
record = {
    "builder": "OverworldGSI",
    "kind": "aosp-source-compiled-gsi",
    "source": "https://android.googlesource.com/platform/manifest",
    "branch": branch,
    "lunch_target": target,
    "image": filename,
    "image_size_bytes": image.stat().st_size,
    "sha256": digest,
    "note": "Generic source build, not proof of compatibility with an individual device.",
}
(dist / "build-info.json").write_text(json.dumps(record, indent=2) + "\n")
PY
# Publish only compressed image, checksums, and build provenance.
rm "$DIST_DIR/$filename"
echo "Built source-compiled GSI: $DIST_DIR/$filename.xz"
