# Status indicator

AgentBridge can display subscription usage in the macOS menu bar or the Windows and Linux system tray while its gateway is running. The dashboard's **Status indicator** page controls the display on the machine running the gateway.

## Start and configure

```sh
agentbridge start
agentbridge dashboard
```

The indicator is enabled by default. On **Status indicator**, you can turn it off or on, choose one or two providers, select a display style and refresh interval, then save. Changes reach the indicator on its next poll; hiding it does not stop the gateway or usage tracking. If you started with `--no-tray`, restart without that option to use the indicator. Install and sign in to the relevant agent CLIs separately; available usage data and reset times depend on the provider and platform.

- **Usage bars:** the top bar represents the 5-hour window and the lower bar represents the weekly window. Both show remaining capacity, so they shrink as usage increases. Select up to two providers.
- **Compact icon:** shows the AgentBridge mark. Click it to see available provider usage and reset times.

Click the indicator for details, provider selection, dashboard access, and refresh. A missing value is shown as unavailable; it does not mean the limit is zero. The Windows and Linux tray uses compact graphics, with percentages in its menu. An always-visible desktop widget is not currently available.

The Linux tray requires a supported graphical X11 desktop with a system tray. Windows and Linux packages pass CI smoke tests, but interactive desktop and provider login behavior still needs real-device testing. If a tray helper fails to start, the gateway can continue running; check `~/.agentbridge/tray.log`.

## Source-based macOS helper

The packaged CLI starts the native macOS helper automatically. For a source checkout, `./menubar/build.sh` builds the helper and `./manage-service.sh menubar {start|stop|restart|status|build}` manages it separately. The source service and the packaged CLI are separate launch methods; avoid running both gateways on the same port.
