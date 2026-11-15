# Releases

For maintainers. Users can get the latest build from the [Releases page](https://github.com/guna81/agent-bridge/releases/latest) or with `agentbridge update`.

## How a release is built

The release workflow (`.github/workflows/release.yml`) builds self-contained archives for macOS Apple Silicon, Linux x86-64 and Windows x86-64. It tests the packaged gateway and dashboard on each target runner, then attaches the archives (`agentbridge-<platform>.tar.gz`) and their SHA-256 files to a GitHub Release.

A manual workflow run builds downloadable CI artifacts **without** publishing a release.

## Publishing

1. Merge the changes to the default branch and run the workflow manually.
2. Test the packages on real desktops: macOS login startup, the tray on Linux X11 and Windows, CLI provider detection, and install/upgrade.
    - On macOS, log out and back in, confirm the gateway and visible indicator start, and check the LaunchAgent's last exit code and `~/.agentbridge/autostart.log`.
    - Test recovery after stopping the helper, and verify repeated starts don't duplicate it.
3. Create and push a tag on the reviewed commit, e.g. `v0.3.6`. It must be `vMAJOR.MINOR.PATCH` and greater than the previous release.

The tag starts the workflow and stamps the CLI and dashboard version automatically. The release is created only if all three builds and the full CI workflow succeed on the tagged commit.

!!! note
    The CI smoke test uses `--no-tray`. It checks that the macOS helper is packaged but not interactive tray behaviour, login startup or provider login.

## Installers and forks

The installers fetch assets from the latest release of the repository configured in the scripts. For forks, set `AGENTBRIDGE_REPOSITORY=owner/repo` or change the default repository and README URLs.

Installers keep old release directories and launcher backups. They don't stop a running gateway, restart it, or remove user data.

## Signing

SHA-256 files detect download errors but come from the same release as the archives, so they don't authenticate the publisher. Binaries are currently unsigned. Set up Apple Developer signing/notarisation and Windows code signing before presenting releases as signed or trusted by the platform.

## Documentation site

The guide is written in Markdown in `docs-src/` and rendered to static HTML in `docs/guide/`, which is committed and deployed with the landing page by `.github/workflows/pages.yml`. After editing any page, regenerate the HTML:

```sh
pip install markdown pymdown-extensions
python3 scripts/build-guide.py
```
