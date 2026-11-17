# SparkyFitness for Mochilab

This is a fresh-install package with app ID `mochilab-sparkyfitness`.
It does not replace `denny-sparkyfitness` or the official `sparkyfitness` app.
Do not install two packages that use port 3019 on the same host.

## Sources and package

- Stable application: [v1.12.1](https://github.com/CodeWithCJ/SparkyFitness/releases/tag/v1.12.1), released 2026-11-10.
- Package source: [commit 324d48d](https://github.com/CodeWithCJ/SparkyFitness/tree/324d48d5c8835d4726d5e22c16fcbe3b9298bc48/umbrel/sparkyfitness).
- Application source: [commit 39d9ca2](https://github.com/CodeWithCJ/SparkyFitness/tree/39d9ca2d13c2a1b9f64e4be793b2f23433489d0c).
- [Upstream Umbrel guide](https://codewithcj.github.io/SparkyFitness/install/umbrel).
- Exact adaptation: [provenance](sparkyfitness-provenance.json).

The release tag still contains the previous Umbrel image pins.
The package source commit contains the reviewed v1.12.1 pins.
All four images retain upstream digest pins and support Linux amd64 and arm64.
The database stays on PostgreSQL 18.3-alpine.

The Mochilab adaptation changes the app ID, container references and exported variable names.
The adaptation declares `storage.dataRoot: data` and adds the community submitter and icon.
The `submission` URL credits upstream's real package PR. It is not a Mochilab PR.
The full upstream non-commercial license is included with the package and vendored updater.

## Compatibility and limits

The inspected device reports umbrelOS 2.0.0 on Intel x86-64.
The installed-app result contains OpenBot and no SparkyFitness package.
That result is not a scan for unmanaged containers or listening ports.
Verify port 3019 before installation.

The package uses native Umbrel gateway configuration and service-health dependencies.
The backend runs as UID/GID 1000 and stores uploads, backup archives and temporary uploads under `data/`.
The database uses `data/postgres` mounted at `/var/lib/postgresql` for PostgreSQL 18.
An isolated restore test must confirm directory ownership and backend startup on the target Umbrel release.

The outer Umbrel login is disabled, following the upstream package.
Anyone who can reach port 3019 can reach the SparkyFitness sign-in page.
Create the first administrator account before sharing access.
Some upload URLs are public to anyone who knows the URL, as described in the upstream guide.
Do not expose the app through a new tunnel or public hostname as part of package installation.

Mobile release builds need trusted HTTPS.
The upstream guide describes Umbrel's local certificate, but mobile TLS has not been tested on this device.
LAN HTTP sign-in, mobile TLS, Tor origins and Garmin sync remain runtime checks.
The umbrelOS 2.0.0 source assigns `APP_HIDDEN_SERVICE` after sourcing app exports.
The upstream Tor-origin export therefore needs a real Tor test before Tor support is claimed here.
No Tor setting is changed by this package preparation.

## Database migration and recovery

The backend applies SQL migrations before loading the HTTP server.
The release source uses a database advisory lock during initialization.
Each SQL file and its migration record commit in one transaction.
A later migration can fail after earlier files have committed.
This design does not make downgrades safe.

The current backup code exports a logical database dump and uploads.
The release backend contains PostgreSQL 18 client tools.
The isolated acceptance test below also exercises the real application backup and restore endpoints.
This proves recovery of synthetic data with preserved test secrets, not recovery of an owner's Umbrel seed.

Before each installed-app upgrade:

1. Review the upstream release notes and new migration files.
2. Create a matching logical database dump and upload backup during a controlled write-free interval.
3. Retain the complete previous app package, image digests and app data.
4. Verify the archive checksums and restore into an isolated test instance.
5. Check sign-in, uploads, schema version and a synthetic record after restoration.
6. Obtain target-specific approval before stopping or updating the live app.

An online copy of the raw PostgreSQL directory is not a verified database backup.
Use a stopped database or a PostgreSQL-aware backup for physical copies.
Restore a matching old database, uploads and secrets when rolling back an application version.
Do not point an old image at a database that a newer release has migrated.

Four secrets derive from the Umbrel device seed and the app ID.
The synthetic export test confirms stable, distinct values for the same identity.
The app data directory does not contain these derived values.
Confirm the secure seed/secret recovery method before relying on recovery onto another device.
Changing the app ID or device seed changes database passwords, credential encryption and session/2FA secrets.
Do not print these values or put them in this repository.

### Existing Denny installations

Denny's inspected package uses v0.16.1, PostgreSQL 15 and a different database layout.
It also uses different database names, credentials and authentication settings.
The later application introduces Better Auth migrations.
Do not mount Denny's PG15 directory into this PG18 container.
Do not assume old encrypted provider credentials remain readable with newly derived keys.

If Denny data must be retained, prepare a separate, approved migration on a clone.
Preserve the old instance and securely retain its keys before exporting data.
Test the PG15 logical export, role/name mapping, application migrations, credentials, sign-in and uploads on the clone.
No Denny migration has been executed or certified by this package work.

## Update process

The pinned upstream updater is vendored in `tools/vendor/sparkyfitness/`.
The local wrapper writes only a review candidate.
The wrapper allows a newer stable application version, release notes and the three application image pins.
The wrapper blocks PostgreSQL changes, mounts, proxy settings, secret configuration, downgrades and same-version repins.
The upstream resolver requires both amd64 and arm64 images before writing a candidate.
Database updates and other package changes require a separate review.

Check for a release without writing files:

```sh
python tools/sparkyfitness_release_plan.py
```

Prepare a local release candidate:

```sh
python tools/sparkyfitness_release_plan.py --prepare-latest
```

Python needs PyYAML; candidate generation also needs Node 24 and network access to GitHub and Docker Hub.
There is no LLM, paid API or new account requirement.

The prepared workflow **Prepare a SparkyFitness release review** runs only when dispatched on `main`.
It opens a draft PR and never merges or installs.
The repository must permit GitHub Actions to create PRs.
PRs made with `GITHUB_TOKEN` do not trigger ordinary PR checks.
Manually run **SparkyFitness package checks** on the generated branch before review.
The checks include disposable containers, API login, restart persistence and synthetic backup/restore.
They do not install the app on the owner's Umbrel.

Recurring release checks must be an owner-approved OpenBot routine.
No GitHub cron, OpenBot routine or automatic merge is enabled by this candidate.
A suitable routine checks the wrapper's read-only result and reports a new stable version to the owner.
Creating a draft PR, merging and updating the host remain separate actions.

## Validation and release gate

Local checks cover package invariants, deterministic synthetic exports, candidate safety, Compose rendering and published image digests.
The official Umbrel linter is pinned to `067355c29a3846b5261e6d5fde8c1e956e98551b`.
The Compose fixture is the configuration-only gateway overlay from umbrelOS 2.0.0.
It is never a runtime proxy image.

On 2026-11-17, the [isolated GitHub Actions acceptance run](https://github.com/mochingub-kub/mochilab-openbot-store/actions/runs/44040573471)
passed with the published v1.12.1 images:

1. Fresh PostgreSQL 18 startup, 305 application migrations and backend readiness.
2. First-account administrator creation and password sign-in through the packaged frontend's HTTP API.
3. The application's logical database and upload backup, downloaded through its authenticated endpoint.
4. In-place restoration after changing a database marker and an upload; both original values returned.
5. Restart persistence, successful sign-in and the same migration count after all application containers restarted.
6. Restoration into a second fresh instance using the same synthetic secrets; the original account and upload returned.

Both instances used separate temporary data directories and networks on an ephemeral amd64 runner.
The acceptance script runs only in GitHub Actions and cleans only its own test containers and data.
The downloaded evidence artifact reports six passes and no cleanup errors.
The owner host, existing applications and Denny data were not changed.

Remaining first-install checks are the native Umbrel gateway/browser UI and actual host directory ownership.
Mobile TLS, Tor and Garmin need checks if those features are required.
A native Umbrel seed restore and Denny PG15 migration remain separate, untested operations.
A later application version must pass this acceptance job before release review.

Merge and installation need explicit approval for PR #32 and app `mochilab-sparkyfitness` on the target Umbrel.
The package preparation and isolated acceptance work do not grant that approval.
