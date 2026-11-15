# Release candidate validation — 14 November 2026

No changes have been pushed, deployed, or published. The installed application has not been replaced by this candidate.

## Automated checks

- macOS backend: 198 passed, 6 skipped (four opt-in real-CLI tests and two native Windows tests).
- Frontend: seven behavioral tests passed; TypeScript and production build passed.
- Linux ARM64 Docker: 198 passed, 6 skipped.
- Linux x86_64 Docker under emulation: 199 passed, 6 skipped, including the added upgrade regression. PyInstaller package build and isolated gateway/dashboard smoke test passed. This is container validation, not minimum-distribution or desktop compatibility validation.
- Linux ARM64: PyInstaller package built and isolated gateway/dashboard smoke test passed.
- macOS ARM64: native Swift indicator and PyInstaller package built; isolated gateway/dashboard start, HTTP response, status, and stop smoke test passed.
- Real Codex: 5/5 checks passed, including nonstreaming, streaming, token usage, and ledger recording.
- Real Claude: 6/6 checks passed, including authentication, nonstreaming, streaming, token usage, and ledger recording.
- Real Antigravity: 7/7 checks passed, including pipe/PTY capture, nonstreaming, streaming, usage, and ledger recording.
- Added a regression for upgrading an old macOS LaunchAgent: verifies reload order, process-group preservation, and unchanged user settings. Startup and wrapper tests pass separately (22 tests).
- The service wrapper test exercises install/start/restart/uninstall delegation without registering actual services.

Windows native terminal tests are configured in CI but have not run here. Running the existing remote workflow would test remote source rather than these uncommitted changes; no remote workflow was triggered.

## Manual candidate check on this Mac

Run from the repository root. These commands use separate data and port 43188 and do not change login startup:

```sh
AGENTBRIDGE_DISABLE_AUTOSTART=1 AGENTBRIDGE_HOME="$PWD/build/manual-test-data" ./build/release/agentbridge/agentbridge start --port 43188
AGENTBRIDGE_HOME="$PWD/build/manual-test-data" ./build/release/agentbridge/agentbridge dashboard
```

1. Confirm the candidate indicator appears. The existing installation may show a second icon; use the candidate dashboard on port 43188.
2. In Status indicator settings, hide and show the indicator; verify the gateway stays responsive while hidden.
3. Switch between bars and compact style; select one and two providers; change refresh interval.
4. Refresh the page and confirm settings persist.
5. Verify the menu displays usage or a clear unavailable state and opens the candidate dashboard.
6. Use the dashboard Connect flow for installed providers; verify successful login, cancellation, and an invalid input error where supported. This may use your local provider login.
7. Stop the candidate and confirm its indicator disappears:

```sh
AGENTBRIDGE_HOME="$PWD/build/manual-test-data" ./build/release/agentbridge/agentbridge stop
```

Do not run `agentbridge update` during candidate testing; that would install the published release rather than this local build.

The candidate archive is `build/artifacts/agentbridge-macos-arm64.tar.gz`; its adjacent `.sha256` file records the checksum. It is a local test build, not a published/notarized release.

## Manual macOS reboot check

This checks the repaired login configuration of the existing installed application, not an installation of the candidate.

1. Stop the isolated candidate above.
2. Run `agentbridge autostart status`; confirm enabled.
3. Restart the Mac and sign in; do not run `agentbridge start` manually.
4. Confirm exactly one installed AgentBridge indicator appears and its dashboard opens.
5. Run `agentbridge status`; confirm ready. Check `~/.agentbridge/autostart.log` and `~/.agentbridge/status-bar.log` if startup fails.
6. Confirm `~/Library/LaunchAgents/com.ai-credit-proxy.plist` is absent; its earlier backup is in `~/.agentbridge/login-backup`.

## Other manual environments

- Windows: native terminal CI must pass first. Test installed sign-in startup, indicator visibility, provider login/input/resize/cancel, and process cleanup after quit.
- Linux: test the actual x86_64 release on a supported graphical X11 desktop; confirm login startup, tray menu, and provider login. Headless Docker does not verify a desktop tray.
- Gemini was not installed and remains unverified.

Production approval remains pending these platform and manual checks.
