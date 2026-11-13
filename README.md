# Orca → Themis

Python plugin for OrcaSlicer 2.5.x, tracked by [BIZ-151](https://linear.app/deviant-mushroom/issue/BIZ-151).

This repository is the plugin workspace. The Themis backend remains in its own repository.

Repository: [mgomezdev/themis-orca-plugin](https://github.com/mgomezdev/themis-orca-plugin).

The development wheel provides a docked panel with paste-friendly API-key settings, connection testing, and background
reference loading. The [send workflows](docs/send-workflows.md) create plate jobs, import plates/objects into new or
existing projects, and send captured raw G-code to jobs or projects. Geometry includes footprint eligibility, optional
filaments/presets, target overrides and ordered printer preferences. Saved send identities support lookup, retry and
updates without duplicating work. Deploy [Themis PR #199](https://github.com/mgomezdev/themis/pull/199) first.
Actual Orca host verification remains deferred; see the [acceptance checklist](docs/roadmap.md).

## Branches

- `main`: release history.
- `develop`: integration branch and target for feature pull requests.
- `feature/biz-<number>-<description>`: work branched from `develop`.
- `release/<version>`: release preparation; merge into `main` and back into `develop`.
- `hotfix/<description>`: urgent fixes from `main`; merge into both long-lived branches.

Keep issue work on feature branches. Tag releases on `main`. Gitflow does not require an extra Git extension.

## Development

See [the plugin guide](docs/orca-plugin.md) for setup, installation, current capabilities, and limitations.
