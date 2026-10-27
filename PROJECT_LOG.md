# PROJECT_LOG.md — ATC subsystem

## 2026-10-27 — repo scaffolded
- Created the ATC dev repo at `vCity/ATC` (standalone; ports into airfield later).
- Dev range blueprint `ARBITR_ATC_DEV` (5 VMs, one FCC /24; no security stack,
  no DC/Windows, no fuel farm). Strip-down decisions recorded in the blueprint
  header + the design doc §8.
- Plumbing: ansible.cfg, hosts, requirements.yml, site.yml (phases 00→30),
  deploy.sh (3-attempt), build_tarball.sh (→ atc_dev.tgz).
- group_vars/atc.yml: airfield params (fictional KBAX), epoch clock, feed/ports,
  feature toggles. host_vars for the 4 managed hosts.
- Roles: common (lean Linux base), atc_inject (feed — working SBS stub),
  atc_core (readsb + tar1090 + FDP; FDP serves strips from aircraft.json),
  atc_weather (METAR stub), atc_cwp (kiosk).
- Known gaps to first green: readsb .deb staging (ng_raw), tar1090 + offline
  tiles, Beast DF17 feed, FDP landing-detection/fuel trigger. See README phases.
