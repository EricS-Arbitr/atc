# ATC — Air Traffic Control cyber-range subsystem

A virtual ATC surveillance + flight-data system for the Blackstone Auxiliary
Field range, developed here against a **scaled-down dev range** and ported into
`airfield-range` / `airfield-stacked` once proven.

- **Design:** [`docs/atc_cyber_range_project_design_document.md`](docs/atc_cyber_range_project_design_document.md)
- **Dev range blueprint:** [`dev_range_blueprint/blueprint.yml`](dev_range_blueprint/blueprint.yml) (`ARBITR_ATC_DEV`, 5 VMs)
- **Build/deploy contract + conventions:** [`CLAUDE.md`](CLAUDE.md)

## The dev range (5 VMs, one subnet)

| Host | Image | Prod IP | Role |
|---|---|---|---|
| `ansible` | RC_NG_Ansible 2.0.4 | — | controller (runs deploy) |
| `dev-rtr` | RC-VyOS-Router 1.1.0 | `172.31.5.1` | FCC gateway |
| `atc-radar` | Ubuntu Server 22.04.5 | `172.31.5.10` | feed + readsb + tar1090 + FDP |
| `atc-station` | Ubuntu Desktop 22.04.5 | `172.31.5.12` | CWP kiosk + display |
| `atc-weather` | Ubuntu Server 22.04.5 | `172.31.5.11` | METAR/TAF feed |

No security stack, no DC, no Windows, no fuel farm — all-Linux, `/etc/hosts`
for name resolution.

## Build & deploy

```bash
./build_tarball.sh          # -> atc_dev.tgz (commit it; controller deploys the tarball)
# on the controller (tarball extracted to /etc/ansible):
./deploy.sh                 # galaxy install + site.yml (3-attempt retry)
```

The blueprint's `download-range-vars-script` wgets `atc_dev.tgz` from
`github.com/EricS-Arbitr/atc` (pinned to a commit SHA — branch URLs are
CDN-cached) through the mgmt proxy. Re-pin the SHA whenever the tarball changes.

## Build phases & current status

| Phase | What | Status |
|---|---|---|
| P0 | base (common: hostname, /etc/hosts, proxy, chrony) | **scaffolded, works** |
| P1 | ADS-B feed engine (`atc_inject`) | **working stub** — SBS emit; Beast DF17 = TODO |
| P2 | readsb ingest (`atc_core/readsb`) | **dev: upstream install** (wiedehopf); air-gap toggles to a pinned ng_raw .deb |
| P3 | tar1090 offline (`atc_core/tar1090`) | **TODO** — vendor tar1090 + offline tiles from Nexus |
| P4 | FDP strips + landing detection (`atc_core/fdp`) | **working stub** — strips from aircraft.json; landing/fuel = TODO |
| P5 | CWP kiosk (`atc_cwp`) | **scaffolded** — .deb browser pin = TODO |
| P6 | fuel requisition | **out of dev range** (develop vs the real farm in airfield) |

See each role's `tasks/` for the `# TODO` seams, and `UPSTREAM_FIXES.md`.
