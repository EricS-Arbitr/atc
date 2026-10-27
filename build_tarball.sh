#!/usr/bin/env bash
# Bundle the ATC dev range into atc_dev.tgz. The controller deploys from this
# tarball (see dev_range_blueprint/blueprint.yml download-range-vars-script),
# NOT a git pull — so rebuild + commit the tarball with every code change.
set -euo pipefail

cd "$(dirname "$0")"
OUT="atc_dev.tgz"

# Everything the controller needs at /etc/ansible. docs/, dev_range_blueprint/
# and the tarball itself are NOT bundled.
INCLUDE=(
  ansible.cfg
  requirements.yml
  hosts
  site.yml
  deploy.sh
  playbooks
  roles
  group_vars
  host_vars
  sim-data
)

# Optional: syntax-check if ansible is available locally.
if command -v ansible-playbook >/dev/null 2>&1; then
  echo "Syntax check..."
  ansible-playbook site.yml --syntax-check >/dev/null && echo "  OK" || {
    echo "  site.yml failed --syntax-check; refusing to build." >&2; exit 1; }
fi

echo "Bundling ${OUT}..."
# COPYFILE_DISABLE stops macOS bsdtar emitting AppleDouble (._*) + xattr headers
# that litter the controller's /etc/ansible on extract.
COPYFILE_DISABLE=1 tar --no-xattrs \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' --exclude='._*' \
    -czf "$OUT" "${INCLUDE[@]}"
echo "Wrote ${OUT} ($(du -h "$OUT" | cut -f1))"
tar tzf "$OUT" | head
