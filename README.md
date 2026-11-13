# Orca → Themis

Python plugin for OrcaSlicer 2.5.x, tracked by [BIZ-151](https://linear.app/deviant-mushroom/issue/BIZ-151).

This repository is the plugin workspace. The Themis backend remains in its own repository.

Repository: [mgomezdev/themis-orca-plugin](https://github.com/mgomezdev/themis-orca-plugin).

The BIZ-379 development wheel provides a docked Themis panel with masked URL/API-key settings,
connection testing, current-plate display, and background reference-data loading. Plate sending
is pending; see [the roadmap](docs/roadmap.md). Actual Orca host verification is deferred.

## Branches

- `main`: release history.
- `develop`: integration branch and target for feature pull requests.
- `feature/biz-<number>-<description>`: work branched from `develop`.
- `release/<version>`: release preparation; merge into `main` and back into `develop`.
- `hotfix/<description>`: urgent fixes from `main`; merge into both long-lived branches.

Keep issue work on feature branches. Tag releases on `main`. Gitflow does not require an extra Git extension.

## Development

See [the plugin guide](docs/orca-plugin.md) for setup, installation, current capabilities, and limitations.
