# Releases

## Getting the latest version

Download the latest build from the [Releases page](https://github.com/guna81/agent-bridge/releases/latest), or update from the command line:

```sh
agentbridge update
```

Builds are available for macOS Apple Silicon, Linux x86-64 and Windows x86-64. Each archive (`agentbridge-<platform>.tar.gz`) comes with a SHA-256 file.

## What an update does

Installers keep old release directories and launcher backups. They don't stop a running gateway, restart it, or remove your data. After updating, restart the gateway to run the new version.

## Unsigned builds

Binaries are currently unsigned, so macOS or Windows may warn you the first time you open one. Download only from the project's Releases page before allowing it.

The SHA-256 files catch corrupted downloads. They come from the same release as the archives, so they don't prove who published it.
