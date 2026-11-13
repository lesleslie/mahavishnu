# Runbook: Disable llama-server autostart

Keep the local llama-server config installed, but stop it from starting at login
or boot on this Mac. Use this when memory pressure matters and Bifrost can route
through cloud fallbacks instead.

## Desired state

- `~/Library/LaunchAgents/com.bodai.llama-server.plist` stays on disk
- launchd is disabled for `com.bodai.llama-server`
- `settings/local.yaml` sets `bifrost.local_provider_enabled: false`

## Disable it

```bash
uid=$(id -u)
label=com.bodai.llama-server
plist="$HOME/Library/LaunchAgents/$label.plist"

launchctl bootout "gui/$uid" "$plist" || true
launchctl disable "gui/$uid/$label"
```

Confirm the disabled bit:

```bash
launchctl print-disabled "gui/$uid" | rg "$label"
```

## Re-enable it later

```bash
uid=$(id -u)
label=com.bodai.llama-server
plist="$HOME/Library/LaunchAgents/$label.plist"

launchctl enable "gui/$uid/$label"
launchctl bootstrap "gui/$uid" "$plist"
```

If you want local routing again, change `settings/local.yaml` back to:

```yaml
bifrost:
  local_provider_enabled: true
```

If bootstrap fails, verify the plist path and model path before retrying.
