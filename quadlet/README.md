# Quadlet units (optional, Linux hosts only)

The stack already runs systemd *inside* the appliance container, which is what
makes it behave identically on macOS, Windows and Linux. These units are the
second, optional layer: the **host's** systemd supervising the containers
themselves, so the stack survives a reboot with no one logged in.

This is the "systemd all the way down" story — systemd managing services inside
the container, and systemd managing the container.

## Install

```bash
mkdir -p ~/.config/containers/systemd
cp quadlet/*.container quadlet/*.network quadlet/*.volume ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start localaimcp-appliance.service

# survive logout
loginctl enable-linger "$USER"
```

## Check

```bash
systemctl --user status localaimcp-appliance.service
journalctl --user -u localaimcp-appliance.service -f
```

## Notes

- Quadlet generates the units at `daemon-reload`; you never write `.service`
  files by hand. `podman generate systemd` is deprecated in favour of this.
- Unit names come from the filename: `localaimcp-appliance.container` becomes
  `localaimcp-appliance.service`.
- Requires Podman 4.4+ (5.x recommended).
- These replace `podman compose up`, they do not complement it. Use compose
  while iterating; use Quadlet for a machine that should just keep running.
- `NREL_API_KEY` is read from `%h/.config/localaimcp/env` — create it with
  `mkdir -p ~/.config/localaimcp && cp .env ~/.config/localaimcp/env`.
