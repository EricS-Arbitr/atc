#!/usr/bin/env bash
# ATC dev range deploy. Runs on the Ansible controller (tarball extracted to
# /etc/ansible). Installs Galaxy collections, then runs site.yml with a small
# retry model (a freshly provisioned range often fails the first pass on
# ordering, not faults — the final pass confirms).
set -u

BOOT_DELAY="${BOOT_DELAY:-120}"      # let freshly provisioned VMs finish booting
ATTEMPTS="${ATTEMPTS:-3}"

cd "$(dirname "$0")" || exit 1

# Vault password file does not persist across range spin-ups — fail closed with
# the fix, like the sibling repos. (Dev vault may be plaintext; this only warns.)
if [ ! -f /home/simspace/.vault_pass ]; then
  echo "WARN: /home/simspace/.vault_pass missing. If vault.yml is encrypted, recreate it:"
  echo "  sudo bash -c 'echo -n <PASSWORD> > /home/simspace/.vault_pass && chmod 600 /home/simspace/.vault_pass'"
fi

# Galaxy collections. Dev range has egress; for air-gapped ranges point
# ANSIBLE_GALAXY_SERVER at Nexus ng_raw/galaxy and add --ignore-certs.
ansible-galaxy collection install -r requirements.yml ${GALAXY_EXTRA:-} || true

if [ "$BOOT_DELAY" -gt 0 ]; then
  echo "Waiting ${BOOT_DELAY}s for VMs to finish booting..."
  sleep "$BOOT_DELAY"
fi

rc=1
for i in $(seq 1 "$ATTEMPTS"); do
  echo "===== site.yml attempt ${i}/${ATTEMPTS} ====="
  if [ "$i" -eq 2 ] && [ -f ~/.ansible/retry/site.retry ]; then
    ansible-playbook site.yml --limit @~/.ansible/retry/site.retry
  else
    ansible-playbook site.yml
  fi
  rc=$?
  [ "$i" -ge 3 ] && [ "$rc" -eq 0 ] && break   # attempt 3 is the confirmation
done
exit "$rc"
