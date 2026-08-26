# KOPDES Deployment Plan

## Supported environments

- Ubuntu 22.04
- Ubuntu 24.04
- Debian 12

## Local desktop install

1. Install Python 3.12+, Qt runtime, and system networking tools.
2. Create virtual environment.
3. Install project in editable or wheel mode.
4. Initialize config and SQLite database.
5. Launch desktop entry or CLI command.

## Production packaging

- `install.sh` installs runtime dependencies and creates app launcher assets.
- `uninstall.sh` removes application files but preserves optional database backups.
- Future target formats: `.deb`, AppImage.

## Container support

Container artifacts are provided for CI, tests, and service-layer validation. Desktop networking control from inside a container is limited and should not be treated as the primary production runtime model.

## Upgrade strategy

- Backup SQLite database before schema upgrades
- Preserve encryption key material
- Run schema bootstrap or migration step
- Restart application

## Operational notes

- Running network actions may require `sudo`, PolicyKit, or NetworkManager privileges.
- Health checks and diagnostics should operate under least privilege where possible.
