# Project Design Document: Blackstone Auxiliary Field — ATC Emulation

> **Status:** revised design, 2026-10-27. This supersedes the original single-AI
> draft. It reconciles that draft against the authoritative airfield project
> (`airfield-range/CLAUDE.md`, "JCTE vCity Military Base, Baseline DEV v21") and
> against the reviewer analysis of the original. The six design forks from the
> first revision were resolved by the project owner on 2026-10-27; §8 records
> the outcomes and this document now reflects them throughout.

---

## 1. Project overview

An Air Traffic Control (ATC) surveillance and flight-data subsystem for the
**Blackstone Auxiliary Field** cyber range — a virtual military airfield used to
train and assess military cyber-defense personnel. ATC is one of five bespoke
systems in that range (weather radar, ATC, access control, fuel farm, power
grid). It must *look and behave* like a real airfield surveillance stack: a
synthetic sensor feed drives a radar scope and electronic flight strips over a
continuous, deterministic, loopable exercise cycle.

This is a **defensive** range. We build legitimate target/defense
infrastructure, not attack tooling. Deliberate weaknesses exist only as
**explicit, parameterized scenario knobs that default secure** (§4C, §4E).

### 1.1 Where ATC lives (not a standalone repo)

ATC is **not** a standalone repository. It is a set of roles + `group_vars` +
`sim-data` + playbook plays layered into **`airfield-range/`** (and its stacked
variant **`airfield-stacked/`**), following that project's conventions. Per the
airfield map (`CLAUDE.md` §6–§7) the ATC hosts already exist in the inventory:

**These are the real inventory names/IPs** (verified against
`airfield-range/host_vars/` + `hosts` `[flight_control_center]`, 2026-10-27 —
they differ from the `bs-atc-*` / `.5.13`/`.5.14` placeholders in the airfield
`CLAUDE.md`; the inventory is ground truth):

| Host | Prod IP | Image | Role in this design |
|---|---|---|---|
| `atc-radar` | `172.31.5.10` | Ubuntu **Server 22.04.5** | **Core + feed**: ADS-B feed engine + `readsb` ingest + `tar1090` scope + FDP |
| `atc-station` | `172.31.5.12` | Ubuntu **Desktop 22.04.5** | **CWP**: controller working position (radar + strips kiosk) |
| `fops-flight01`–`04` | `172.31.5.81`–`.84` | **Windows 10** (domain-joined, autologin) | Additional flight-ops display endpoints (4 of them) |

> **No separate injector host is provisioned.** The airfield `CLAUDE.md` sketched
> an `atc-inject` at `.5.13`, but no such host exists in the inventory. The feed
> engine therefore **co-locates on `atc-radar`** (binds `0.0.0.0`, so `readsb`
> connects locally while blue/red taps still attach over the net). If scenario
> realism wants the sensor physically separated, add an `atc-inject` host to the
> blueprint — **this is a blueprint change, flag it first** (§8 note).

Weather (`atc-weather` `172.31.5.11`, Ubuntu Server 22.04.5, NEXRAD/METAR/TAF) is
a **separate sibling system** in the same enclave and inventory group. This
document builds ATC and *consumes* weather at the display layer only; the weather
build has its own sheet.

Every host is **dual-homed** (airfield `CLAUDE.md` §8): a production NIC on
`172.31.5.0/24` (default route via the FCC gateway) and a management NIC on the
hidden control plane `10.255.240.0/20` (gw `10.255.240.1`). Ansible connects
over management (`ansible_host` = mgmt IP). `ip_forward=0` on all ATC hosts
(none are OT bridge hosts). The management plane is never exposed to a scenario
service and never carries workstation→server scenario traffic.

### 1.2 Deployment constraint

The platform provisions base VM images and NICs. **100% of software install,
configuration, and service enablement is via Ansible, idempotently, zero manual
steps.** The range re-deploys and resets to known-good between exercises
(reset is a *separate* playbook — §5.6, not the deploy path).

### 1.3 Network & artifact-sourcing model (read before writing any install task)

- **During development** the range has external internet access, but the
  platform also runs an **in-platform Nexus** (`nexus.dev.ng.simspace.lan`),
  reachable **only through the management proxy `10.255.240.1:3128`** (not
  direct), presenting an **internal-CA cert** (untrusted by default).
- **Target state is air-gapped.** Some customers run air-gapped. Therefore
  **every** artifact ATC needs — packages, source archives, zip/tarballs,
  container images, map tiles, aircraft databases, Python wheels — must
  ultimately be sourced from Nexus, not the public internet. **No task may
  clone from GitHub, hit a PPA/snap store, or download from upstream at deploy
  time.** Build/pin/mirror once; serve from Nexus. The full artifact inventory
  and Nexus layout is §6.
- Consequence for this design: **no community install scripts** (the wiedehopf
  `readsb`/`tar1090` scripts fetch from the internet and build from source as a
  side effect — they violate both the air-gap rule and idempotency). We package
  or pin instead (§4B).

---

## 2. Architecture & VM roles

Three ATC service hosts on the FCC enclave (plus the flight display endpoints
and the sibling weather host). The ATC Linux hosts are provisioned as
**Ubuntu 22.04.5** images (`atc-radar`/`atc-weather` Server, `atc-station`
Desktop — verified in host_vars). The airfield estate is mixed (some 24.04/25
hosts), so per-release apt dists are already a fact of life; ATC targets the
`jammy` dist.

### Service group A: the data engine (on `atc-radar`)
- **Purpose:** generate synthetic ADS-B surveillance for the exercise cycle.
  Runs as its own systemd service on `atc-radar` (co-located — no injector host
  exists; see §1.1).
- **Services (systemd):**
  - Custom Python **trajectory engine** emitting **Beast-format DF17 extended
    squitter** on TCP `30005` (real ADS-B frames, so defenders work genuine
    ADS-B rather than pre-decoded text), **bound to `0.0.0.0`** and accepting
    **multiple concurrent clients** (so local `readsb`, a blue-team tap, and a
    red-team injector can all attach at once — the original localhost/
    single-client design blocked that). Frames cover **identification**
    (callsign + type), **airborne position**, and **velocity**; the Mode-A
    **squawk** is conveyed over the Mode S path `readsb` expects so the scope
    shows it.
  - Also exposes a secondary **SBS/BaseStation** output on TCP `30003` (decoded
    text) for simple human-readable taps and tooling.
  - Optional **independent primary-radar / MLAT** feed (knob
    `atc_primary_radar_enabled`, default `false`) emitting a lower-fidelity,
    independent position so the blue team can build "ADS-B says X, primary says
    Y" cross-check detections.
  - Reads `schedule.json` + the airfield parameter block (§4A).
- **Clock:** epoch-based (§4A) — survives restarts, shared across the range.

### Service group B: processing & display core (on `atc-radar`, `172.31.5.10`)
- **Purpose:** ingest the feed, host the radar scope, run the FDP.
- **Services (systemd):**
  - **`readsb`** in network-only mode, pulling from the local feed engine as a
    `--net-connector 127.0.0.1,30005,beast_in`, and re-serving SBS `30003` +
    `aircraft.json` downstream. No SDR. Config written by Ansible to
    `/etc/default/readsb` (§4B).
  - **`tar1090`** web scope, served by **lighttpd** (tar1090's shipped default)
    — **offline**: map tiles and the aircraft database are served locally from
    Nexus-sourced artifacts, never OpenStreetMap/the internet (§4B, §6).
  - **FDP** (Flight Data Processor) web app — electronic flight strips, dark
    dashboard, SQLite. Learns flights from `readsb`'s `aircraft.json` (live) and
    detects landings from it (§4C). Hosts the fuel-requisition integration
    (§4D) and emits structured audit/access logs for the SIEM (§4E).

### `atc-station` — controller working position (`172.31.5.12`, Ubuntu Desktop 22.04.5)
- **Purpose:** the **trainee/operator** position (the controller's scope). This
  is **not** the blue-team console — defenders work from the SOC
  (`172.31.7.0/24`). It is a dedicated **Linux kiosk**; the `fops-flight01–04`
  general flight-ops workstations are domain-joined Windows 10 instead.
- **Display:** auto-login (the host is already an Ubuntu Desktop image); a
  browser launched full-screen on boot showing **one** operations page that
  splits the screen between the radar (`tar1090`) and the flight strips (FDP) —
  kiosk mode is a single fullscreen window, so "two tabs" is not achievable; the
  FDP serves a combined layout (or the WM places two windows). Browser = a
  **.deb** browser, not a snap (§6) — on Ubuntu 22.04 Firefox/Chromium default to
  snaps, which need the snap store and break air-gapped.

---

## 3. Module layout inside `airfield-range/`

ATC slots into the airfield repo conventions (`CLAUDE.md` §10). No new
top-level repo.

```text
airfield-range/
├── group_vars/
│   └── atc.yml                 # airfield params, host IPs/ports, feature knobs,
│                               #   exercise epoch; single source of truth (§4A)
├── host_vars/
│   ├── atc-radar.yml  atc-station.yml      # existing (atc-weather.yml = sibling)
│   └── fops-flight01.yml … fops-flight04.yml   # existing, Windows 10
├── playbooks/
│   ├── 30-fops.yml             # FCC enclave — invokes the atc_* roles
│   └── 70-injection.yml        # starts/loads the replay feeds (weather, atc, …)
├── roles/
│   ├── atc_inject/             # trajectory engine, systemd, deps (from Nexus)
│   ├── atc_core/               # readsb (.deb/pinned) + tar1090 + lighttpd + FDP
│   └── atc_cwp/                # desktop, .deb browser, kiosk ops page
├── sim-data/atc/
│   ├── schedule.json           # generated, deterministic (§4A)
│   ├── generate_schedule.py    # route-template schedule generator (§4A)
│   └── airfield.yml            # ident, lat/lon, elevation, runways, magvar
└── tests/acceptance/atc/       # one check per build phase (§7)
```

Role/app source (the Python trajectory engine, the FDP) lives under each role's
`files/`/`templates/`, consistent with how `fuel_sim` ships its `fuelsim/`
package.

---

## 4. Subsystem specifications

### A. Trajectory engine & schedule (`roles/atc_inject`, `sim-data/atc/`)

**Exercise clock — epoch-based, not uptime-based.** The original "time since the
service started" design resets the scenario to Day 1 every reboot, crash or
Ansible re-run, and drifts the ATC feed out of sync with the fuel farm and
weather. Instead:

```
cycle_position = (now_utc - atc_exercise_epoch) % atc_cycle_seconds
```

- `atc_exercise_epoch` (a fixed UTC timestamp) and `atc_cycle_seconds` live in
  `group_vars/atc.yml` and are **shared range-wide** so ATC, weather and the
  fuel farm advance on the *same* wall clock.
- `atc_cycle_seconds` default **`172800` (48 h)** to match the airfield replay
  convention (`CLAUDE.md` §9) and the fuel farm's `fuel_timeline_hours: 48`, so
  aircraft movements and `fuel_orders` line up. *(The original draft said 72 h /
  259200 s; reconciled to 48 h — raise it in review if 72 h is required.)*
- **`chrony` is managed on every ATC host** (and should be range-wide) so
  timestamps line up across sensors, strips, fuel DB and the SIEM. **`bs-ntp`
  (`172.31.2.6`) is planned but not yet in the blueprint** — a DNS A record and
  `ntp_server_ip` already point at it, but the host does not exist. Until it is
  added, sync the ATC hosts to the `fops.blackstone.mil` DCs (`172.31.3.11` /
  `.12`, which they already use for DNS and which are authoritative for the fops
  domain), then cut over to `bs-ntp` when it lands.
- **Cycle-wrap behavior is defined, not implicit:** at wrap, any still-airborne
  aircraft are retired cleanly (tracks dropped, a synthetic "end of window"
  gap) and the schedule restarts from offset 0. Define the gap length so the
  scope visibly re-initializes rather than teleporting aircraft.

**Schedule format (expanded).** The original `waypoints`-only object can't feed
flight strips or the fuel trigger. Each flight object carries:

```jsonc
{
  "callsign": "RCH481",
  "icao_hex": "AE1234",         // see hex-DB override in §4B
  "squawk": "1234",
  "ac_type": "C-17",            // drives heavy/fuel logic
  "category": "heavy",          // light | medium | heavy
  "flight_rule": "inbound",     // inbound | outbound | local/pattern
  "origin": "KADW", "destination": "KBAX",   // KBAX = our field (fictional)
  "heavy": true,                // webhook: heavy → fuel requisition on landing
  "fuel_request_gal": 4800,     // optional explicit requisition size
  "departure_offset_s": 3600,   // relative to atc_exercise_epoch
  "route": "arr_rwy33",         // route-template name (see generator)
  "events": [                   // optional scripted events
    { "offset_s": 5400, "squawk": "7700" }   // emergency, etc.
  ],
  "waypoints": [ { "lat": …, "lon": …, "alt_ft": …, "gs_kt": …, "offset_s": …, "on_ground": false } ]
}
```

**Schedule generator (`generate_schedule.py`).** 10 hand-typed flights do not
fill 48–72 h (a realistic shift plan is ~15–25 movements/day). The generator
builds the schedule deterministically from **route templates** (arrival to each
runway end, departure, closed-pattern work, orbits/holds) seeded from
`airfield.yml`, so movements are repeatable and dense. A sample 10-flight
`schedule.json` is fine as a Phase-1 fixture; the generator is the real source.

**Airfield parameters (`sim-data/atc/airfield.yml`).** The original has no
airfield at all — no coordinates, elevation, runway headings or identifier, yet
waypoints, the scope's map center/range rings, and METAR all need them. Define a
variable block (ident, lat/lon, field elevation, magnetic variation, runway
ends + headings, pattern altitude, nav fixes). Blackstone Auxiliary Field uses **fictional**
coordinates not tied to any real airfield — see the starter block in §8.

**Python dependencies** come from Nexus `ng_pypi` (§6), installed into a
**venv** (isolation + determinism; 22.04 still allows system-wide `pip`, but a
venv keeps ATC's deps off the system interpreter and matches the newer estate
hosts where PEP 668 blocks system installs).

### B. Radar core: `readsb` + `tar1090` (`roles/atc_core`)

**Resolve the source contradiction.** The original says "don't build from
source" but then points at the wiedehopf scripts, which *do* build from source
and fetch at runtime. Pick one, air-gap-clean:

- **Recommended: a pinned `readsb` `.deb`**, built once and hosted in Nexus
  `ng_raw` (§6). Ansible installs the `.deb` and **writes `/etc/default/readsb`
  itself** — network-only mode (no SDR), `--net-connector
  127.0.0.1,30005,beast_in` (local Beast in), and the bind/listener options.
  (Alternative: a
  pinned source build pinned to a tag, done inside the role from a
  Nexus-hosted source tarball. Either way Ansible owns the config file; no
  remote script runs.)
- **`tar1090` offline.** `tar1090` and its database are vendored (Nexus
  `ng_raw`), not git-cloned. **Map tiles are hosted locally** (a pinned offline
  tileset served by lighttpd from a Nexus artifact) so the scope renders over a
  real map, not a blank background. Served by **lighttpd** (tar1090's default
  config). *(Airfield uses nginx for web elsewhere; lighttpd keeps tar1090's
  shipped integration intact. Flag if single-web-server consistency is
  required.)*
- **Hex-DB override.** `tar1090`'s aircraft database will mislabel our synthetic
  US-military `AE…` hex codes as whatever real airframe owns that code. **Disable
  the DB lookup or override it** with our own `schedule.json`-derived type/reg so
  the scope shows the aircraft we scripted.
- **Hostnames via inventory.** `readsb`'s `--net-connector` target resolves via
  Ansible-managed `/etc/hosts` entries sourced from inventory IPs (or the IP
  directly) — no reliance on range DNS for the ATC data path.

### C. Flight Data Processor (`roles/atc_core`, FDP app)

- **Data source — resolved.** The FDP reads **`readsb`'s `aircraft.json`** (the
  decoded live feed on `atc-radar`) for the strip list and for **landing
  detection** (altitude/ground-speed/on-ground transition over the field). It
  does **not** read `schedule.json` directly. This is the realistic ATC data
  path *and* it means a spoofed/injected track visibly affects the strips and
  the fuel trigger — which is the point of the cross-system scenario.
- **Stack:** lightweight web server + **SQLite** (portable; **not** reset on
  deploy — §5.6). Dark-mode dashboard: inbound / outbound / local strips.
- **Deliberate vulnerabilities — controlled.** The SQLi in the flight
  search/filter and the unauthenticated status endpoints (e.g.
  `/api/update_squawk`) are **gated behind `atc_vulns_enabled` (default
  `false`)**, each marked clearly in code (`# RANGE-VULN:` + a short rationale),
  and documented in an **instructor answer key**
  (`docs/atc_instructor_answer_key.md`, kept out of trainee-reachable paths).
  Defaults secure, per the airfield guardrail (`CLAUDE.md` §11).

### D. Fuel-farm integration — ATC → fuel requisition

The fuel farm is already built, so this is grounded in its real interface, not a
stub:

- **The seam exists.** `fuel_db` (PostgreSQL 16 + TimescaleDB, `fuel-db`
  `172.16.46.19`, database `fuel_audit`) has a **`fuel_orders`** table:
  `(order_id, tail_no, pad_id, requested_gal, status DEFAULT 'OPEN',
  created_ts)`, and `delivery_txn.order_id` references it. A "fuel requisition"
  is therefore a **row in `fuel_orders`** (status `OPEN`), keyed to a known
  `tail_no`/`pad_id` (seed data in `group_vars/fuel.yml`:
  `AF-2231`/`AF-2232` C-17, `AF-4118`/`AF-4119` KC-135, pads `PAD-A1`…`PAD-B2`).
- **Two points, both approved (owner, 2026-10-27):**
  1. **The fuel sim doesn't yet ingest external orders.** Today `fuel_sim`
     replays a fixed deterministic timeline (`fuel_ops_timeline.jsonl`,
     `order_created` events) and invents its own orders. For ATC to *drive* the
     fuel farm, `fuel_sim` gains an **external-order poll**: it reads
     `fuel_orders` for OPEN rows it did **not** author and dispatches them
     alongside its replay. This is an approved change to the fuel subsystem.
  2. **It crosses the default-deny L3.5 boundary.** FCC (`172.31.5.0/24`, fops)
     → OT Fuel-Sim segment (`172.16.46.0/24`) traverses **`bs-ops-fw`**, which
     is default-deny and today admits "only brokered jump access + historian
     replication" (`CLAUDE.md` §5, §11 — *ask before adding any cross-boundary
     rule*). A fuel requisition needs **one explicit, narrow, logged allow rule**
     (`atc-radar` → the requisition sink only). That single sanctioned IT→OT
     channel is exactly the attack surface the red team probes and the blue team
     must watch — it should be deliberate and minimal, never a broad FCC↔OT
     opening.
- **Chosen mechanism:** the FDP does **not** write Modbus and does **not** open
  a direct psql session across the boundary.
  Instead a **small requisition endpoint/broker** (REST, on the OT side of the
  boundary, or on the historian's read-only replica `bs-ro-hist 172.31.8.5`)
  accepts a signed requisition from `atc-radar` and performs the
  `INSERT INTO fuel_orders`. One firewall rule, one auditable hop, IT kept off
  the OT control plane. DB credentials (`fuel_rw`) stay vaulted on the OT side.

### E. Telemetry & blue-team instrumentation (new — the original had none)

The reviewer correctly flagged that the blue team had nothing to detect *with*.
The airfield already runs **Security Onion 2.4** (distributed grid) as its SIEM
(`CLAUDE.md` §9), so ATC must feed it:

- **Elastic Agent on every ATC host** (`atc-radar`, `atc-station`, and the four
  `fops-flight01–04` Windows endpoints), enrolled into SO Fleet — matches the
  range-wide "Elastic Agent on every Linux/Windows host" rule. The Windows
  flight endpoints also get Sysmon (the range default).
- **Application logs as parsed datasets:** the FDP writes structured audit logs
  (auth events, every `/api/*` call incl. the unauth ones, SQL errors) and
  lighttpd access/error logs; these ship to SO via the local agent. The
  weather-denial and spoofing scenarios need a consumer and an audit trail —
  this is it.
- **Network visibility — already provisioned.** The FCC enclave
  `172.31.5.0/24` is **already mirrored** by **`soc-sensor-fops`**
  (`172.31.7.22`), which GRE-mirrors `bs-ops-rtr` covering Flight-Ops-Services
  `.3`, Flight-Control-Center `.5` and Flight-Ops-Users `.6`; its
  `so_verify_mirror_targets` already includes `atc-radar` (`172.31.5.10`). So
  the ADS-B feed and FDP traffic are already on the wire for Zeek/Suricata — **no
  new sensor or tap is needed**; just confirm the mirror is healthy after deploy.
- **Independent surveillance feed (optional, for cross-check detections).** The
  strongest ADS-B-spoofing detections cross-check the ADS-B track against an
  independent source (simulated **primary radar** or **MLAT**). The optional
  second feed on `atc-radar` (knob `atc_primary_radar_enabled`, default off; §2)
  emits a lower-fidelity independent position so defenders can build "ADS-B says
  X, primary says Y" logic.
- **Weather consumer.** METAR/TAF from `atc-weather` (`172.31.5.11`) must have a
  *display* and a *log* (the FDP or a strip-bay widget consumes and renders it),
  or the "weather denial-of-service" scenario has no observable effect. The
  weather *source* is the sibling `atc-weather` build; ATC owns only the
  consumer/display.

---

## 5. Automation & Ansible constraints

Reuses the airfield project's scaffolding and conventions.

1. **Idempotency.** Every task safe to re-run; no duplicate data; the FDP SQLite
   DB and the schedule are **never wiped on deploy**.
2. **Systemd.** The trajectory engine, FDP, and any broker run as templated
   `.service` units (start on boot, restart on failure).
3. **Variables = single source of truth.** All IPs, ports, paths, the epoch and
   feature knobs live in `group_vars/atc.yml` / `host_vars` — no hardcoded
   IPs/creds in tasks or templates (`CLAUDE.md` §11).
4. **Privilege:** connect as the standard user, `become: true` where needed.
5. **Non-interactive:** `apt-get install -y`, no prompts; and **no network
   fetches at deploy time** (§1.3, §6).
6. **Reset is a separate playbook.** "Easy reset by Ansible" conflicts with
   idempotency if the deploy path wipes state. Deploy is idempotent and
   preserves state; **`playbooks/reset-atc.yml` (or `site.yml --tags reset`)**
   performs the destructive reset (truncate FDP DB, clear tracks, reset the
   cycle). Mirror the fuel/power `--tags reset` scope question
   (data-only vs also-config) — see airfield `CLAUDE.md` §12.
7. **Prerequisites (reuse airfield's):** Ansible/collections pinned in
   `requirements.yml` (`vyos.vyos`, `pfsensible.core`, `ansible.windows`,
   `microsoft.ad`, `community.*`); SSH over the mgmt plane; **`ansible-vault`**
   for all credentials (the `fuel_rw` DB password, any broker token, browser
   autologin). **Testing:** `ansible-lint` + `--syntax-check` + `--check --diff`
   dry run in CI; per-role acceptance checks in `tests/acceptance/atc/` (§7).

---

## 6. Artifact sourcing (Nexus)

Everything ATC installs must resolve to Nexus (`nexus.dev.ng.simspace.lan`)
through the mgmt proxy `10.255.240.1:3128`, trusting/skip-verifying the
internal-CA cert. Build/pin/mirror once; serve air-gapped thereafter.

| Artifact | Nexus repo | Fetcher / note |
|---|---|---|
| OS + XFCE/desktop packages | **apt** (`jammy` dist — ATC hosts are 22.04) | through proxy; mirror the `jammy` release dist (per-release, not a mixed index) |
| **`readsb`** (pinned `.deb`) | `ng_raw` (`installers/atc/`) | built once; `apt`/`dpkg` install; Ansible writes `/etc/default/readsb` |
| **`tar1090`** source + **aircraft DB** | `ng_raw` (`installers/atc/`) | unpacked by the role; no git clone |
| **Offline map tileset** | `ng_raw` (`installers/atc/tiles/`) | served by lighttpd; no OSM at runtime |
| lighttpd | apt | tar1090's shipped web server |
| **Kiosk browser** (a **`.deb`**, e.g. Firefox from the Mozilla apt repo mirrored to Nexus) | apt / `ng_raw` | **not** a snap — snaps need the snap store (air-gap-hostile) |
| Python interpreter + venv wheels (trajectory engine, FDP, broker) | **`ng_pypi`** | `pip --index-url …/ng_pypi/simple --trusted-host …` into a venv |
| Any container image (if the FDP/broker is containerized) | **`nexus-docker`** | `skopeo`/dockerd `insecure-registries`; pin tags, never `:latest` |

> **Dev vs air-gap:** while the range has egress you may stage artifacts
> straight to Nexus; validate the air-gap path by deploying with egress blocked
> (Phase 9, §7) before declaring done. The apt-dist caveat from the SO work
> applies: a single mixed-release apt index is unusable — mirror the **one**
> release dist that matches the chosen Ubuntu baseline.

---

## 7. Phased build plan & definition of done

The original "build it all in one pass, no checkpoints" is replaced by phases,
each with a concrete acceptance test (`tests/acceptance/atc/`). Do not proceed
past a failing gate.

| Phase | Builds | Acceptance test (done = ) |
|---|---|---|
| **P1** | `atc_inject` trajectory engine (on `atc-radar`) + sample 10-flight `schedule.json` | `nc atc-radar 30005` shows **Beast DF17** frames (and `:30003` shows SBS); multiple clients attach at once; clock is epoch-based (survives a service restart without resetting) |
| **P2** | `readsb` (.deb) net-connector + `/etc/default/readsb` | `readsb` `aircraft.json` lists the scripted aircraft with callsign/alt/speed/squawk |
| **P3** | `tar1090` + lighttpd, offline tiles, hex-DB override | scope renders the field + range rings over a **local** map with **egress blocked**; `AE…` tracks show *our* types, not random real airframes |
| **P4** | FDP: strips + landing detection from `aircraft.json`; schedule generator | strips populate inbound/outbound/local; a scripted heavy landing is detected; generator fills a full cycle (~15–25 movements/day) |
| **P5** | `atc_cwp`: autologin desktop, `.deb` browser, combined kiosk ops page | `atc-station` boots to a fullscreen radar+strips page, no snap store, no manual steps |
| **P6** | Fuel requisition (`fuel_sim` external-order poll + one `bs-ops-fw` rule) | a heavy landing creates an `OPEN` row in `fuel_orders`; `fuel_sim` dispatches it; exactly one `bs-ops-fw` rule carries the flow and it is logged |
| **P7** | Telemetry | Elastic Agent enrolled on all ATC hosts; FDP/lighttpd logs visible in SO; FCC traffic visible on the existing `soc-sensor-fops` mirror (Zeek `conn.log` for `172.31.5.0/24`) |
| **P8** | Vuln toggles + instructor answer key; reset playbook | `atc_vulns_enabled=false` by default; reset playbook wipes state idempotently; deploy re-run does **not** wipe state |
| **P9** | Air-gap validation | full deploy succeeds with **egress blocked**, sourcing only from Nexus |

---

## 8. Resolved decisions (owner, 2026-10-27)

The six forks from the first revision were resolved as below; the design above
reflects them.

1. **Linux OS = Ubuntu 22.04.** The ATC hosts (`atc-radar`, `atc-weather`
   Server; `atc-station` Desktop) are **already provisioned as 22.04.5 images**
   in the inventory, which also matches the owner's stated preference. *(This
   corrects the 24.04 answer from the first pass — the airfield `CLAUDE.md` §3.6
   says 24.04, but the actual images are 22.04.5. The estate is mixed
   22.04/24.04/25, so per-release apt dists are already required; ATC targets
   `jammy`.)*
2. **`atc-station` is the Linux controller/trainee kiosk** (Ubuntu Desktop
   22.04.5, `172.31.5.12`), not the blue-team console (defenders use the SOC,
   `172.31.7.0/24`). **`fops-flight01–04` (four, Windows 10, `172.31.5.81–.84`)**
   are domain-joined flight-ops display workstations — they match the fops Win10
   enclave and give the blue team Windows endpoint telemetry + Sysmon.
3. **ATC-only scope.** Weather radar stays a separate sibling build
   (`atc-weather`); ATC owns only the METAR/TAF *consumer* and display.
4. **FDP reads `readsb`'s `aircraft.json`** for strips and landing detection.
   **4b. Fuel link approved:** `fuel_sim` gains an external-order poll
   (dispatches OPEN `fuel_orders` rows it did not author), and exactly **one**
   explicit `bs-ops-fw` allow rule carries `atc-radar` → requisition sink. A
   small requisition broker performs the INSERT; the FDP never writes Modbus or
   opens psql across the boundary.
5. **ADS-B = Beast DF17** (real frames) as the primary feed on `30005`, with SBS
   `30003` kept as a secondary convenience output; the optional **independent
   primary-radar/MLAT** feed is included behind `atc_primary_radar_enabled`
   (default off).
6. **Airfield = fictional.** Blackstone Auxiliary Field uses invented
   coordinates not tied to any real airfield. Starter
   `sim-data/atc/airfield.yml`:

   ```yaml
   # Blackstone Auxiliary Field — FICTIONAL. Coordinates, identifiers and runway
   # data are invented for the range and must NOT be mapped to any real-world
   # airfield or nav database.
   airfield:
     ident_icao: "KBAX"             # fictional
     ident_faa:  "BAX"              # fictional
     name:       "Blackstone Auxiliary Field"
     lat:         38.5000           # fictional reference point
     lon:        -78.5000
     field_elev_ft: 520
     mag_var_deg:  -9.0             # west variation (design value)
     pattern_alt_ft_agl: 1000
     runways:
       - { ident: "02/20", true_hdg: 20,  length_ft: 8000, surface: "asphalt" }
       - { ident: "11/29", true_hdg: 110, length_ft: 5000, surface: "asphalt" }
     nav_fixes: []                  # populated by the route templates (§4A)
   ```

   These are design seeds — adjust freely; the only hard rule is that they stay
   fictional and self-consistent (waypoints, map center and range rings all
   derive from this block).

### 8.1 One item still open — the injector host

The inventory has **no `atc-inject` host** (the airfield `CLAUDE.md` sketched one
at `.5.13`, but it was never provisioned). This design defaults to
**co-locating the feed engine on `atc-radar`**, which is buildable today with no
blueprint change. The alternative — a dedicated `atc-inject` VM for a physically
separate sensor, better for the red-team injection scenario — is a **blueprint +
inventory change** and should be decided before Phase 1 if wanted. Default:
co-locate; add the host only on request.
