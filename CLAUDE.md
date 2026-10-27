# CLAUDE.md — ATC subsystem (dev repo)

Guidance for building the ATC system with Claude Code. Read this first, then
the design doc (`docs/atc_cyber_range_project_design_document.md`).

## What this is

A standalone dev repo (root = `vCity/ATC`) for iteratively building the ATC
surveillance + flight-data system against a **scaled-down dev range**
(`dev_range_blueprint/blueprint.yml`, `ARBITR_ATC_DEV`). Once proven, the roles
port into `airfield-range/roles/` + `airfield-stacked/roles/` per the
role-sourcing policy (COPY, don't reference). Host names / IPs / mgmt IPs here
match the real airfield Flight-Control-Center so the port is clean.

## Authority order

owner decisions → design doc → this file → per-role TODOs.

## Deploy model (same as the sibling ranges)

- Controller deploys from **`atc_dev.tgz`**, not a git pull. **Rebuild +
  commit the tarball with every change** (`./build_tarball.sh`).
- Blueprint `download-range-vars-script` wgets the tarball through the mgmt
  proxy `10.255.240.1:3128`; pin it to a commit SHA (branch URLs are
  CDN-cached). Repo: `github.com/EricS-Arbitr/atc`.
- `site.yml` imports phases in order: `00-base` → `10-radar` → `20-weather`
  → `30-cwp`. `deploy.sh` runs up to 3 attempts (attempt 3 confirms).
- **Reset is a SEPARATE playbook** (`playbooks/reset-atc.yml`), never in the
  deploy path — a re-run must never wipe exercise state (idempotency).

## Hard rules (from the airfield project + design doc)

1. **No deploy-time internet.** No git clone, no PPA/snap store, no upstream
   downloads in a task. Everything is staged/pinned from Nexus
   (`nexus.dev.ng.simspace.lan`, via the proxy, internal-CA cert → skip-verify).
   Dev range has egress; **validate the air-gap path** before "done".
   - apt → `jammy` dist (ATC hosts are 22.04); pip → `ng_pypi`
     (`atc_pip_index_url`); tarballs/.deb/tiles → `ng_raw`.
   - **Explicit dev exception:** readsb installs from upstream over the
     internet (`atc_readsb_install_method: upstream_script`) while iterating;
     air-gap flips to `nexus_deb` + a pinned `ng_raw` .deb. Ansible writes
     `/etc/default/readsb` in both paths — never a community script's config.
2. **`group_vars`/`host_vars` are the single source of truth.** No hardcoded
   IPs/creds in tasks/templates. The ATC centerpiece is `group_vars/atc.yml`
   (airfield params, epoch clock, feed/ports, feature toggles).
3. **Secrets via `ansible-vault`** (`group_vars/all/vault.yml`). The dev vault
   may be plaintext placeholders; ENCRYPT before any non-lab use. Never commit
   the password; `/home/simspace/.vault_pass` does not persist across spin-ups.
4. **Deliberate vulnerabilities default secure** (`atc_vulns_enabled: false`),
   are marked `# RANGE-VULN:` in code, and documented in an instructor answer
   key kept out of trainee-reachable paths.
5. **Epoch-based clock** (`atc_exercise_epoch` + `atc_cycle_seconds`), shared
   range-wide so the feed, strips and (later) fuel line up. Never count from
   service start.
6. **Log workarounds in `UPSTREAM_FIXES.md`** the same turn they land.

## Repo layout

```
ATC/
├── ansible.cfg  hosts  requirements.yml  site.yml  deploy.sh  build_tarball.sh
├── group_vars/{all/main.yml, all/vault.yml, linux.yml, vyos.yml, atc.yml}
├── host_vars/{atc-radar,atc-station,atc-weather,dev-rtr}.yml
├── playbooks/{00-base,10-radar,20-weather,30-cwp,reset-atc}.yml
├── roles/
│   ├── common        # hostname, /etc/hosts, apt proxy, chrony, atc user (lean, Linux-only)
│   ├── atc_inject    # ADS-B feed engine (SBS stub; Beast DF17 = TODO) — atc-radar
│   ├── atc_core      # readsb + tar1090 + FDP (tasks split) — atc-radar
│   ├── atc_weather   # METAR/TAF feed — atc-weather
│   └── atc_cwp       # kiosk display — atc-station
├── sim-data/atc/{airfield.yml, schedule.json, generate_schedule.py}
├── dev_range_blueprint/blueprint.yml
├── docs/atc_cyber_range_project_design_document.md
└── atc_dev.tgz       # built artifact (committed)
```

## Current state (scaffold)

Deployable base + role seams with working stubs for the feed and the FDP, so
there is an end-to-end thread to iterate on. The significant TODOs are tracked
in `README.md` (phase table) and inline as `# TODO` in each role. The biggest
blockers to a first green P2/P3 are: a pinned **readsb `.deb`** staged in
`ng_raw` (`atc_readsb_deb_url`), and vendoring **tar1090 + offline tiles**.
