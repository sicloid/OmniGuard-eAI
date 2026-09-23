# Pi 5 management boundary (KAN-44 preparation)

This is an operator checklist for Şükrü's physical Pi 5. It is not a record of
installation or a passed KAN-44 gate. Run it only when the device is accessible,
and attach redacted command outputs and the date to KAN-44.

1. Record the Pi identity and environment: `uname -srmo`, `/etc/os-release`,
   `python3 --version`, `tailscale version`, and the device-tree model string.
   Do not copy laptop results into the Pi evidence set.
2. Bring Tailscale up for **device management only**. Do not enable a subnet
   router, exit node, lab bridge, NAT or host-side veth for OmniGuard. Tailscale's
   [CLI reference](https://tailscale.com/docs/reference/tailscale-cli/up) says
   `--advertise-routes` exposes subnets; an empty value clears a previous route
   setting. Check the current setting with `tailscale get --json advertise-routes`
   and inspect the Pi's route advertisement in the Tailscale admin console.
   Both must show **no advertised subnet routes**, especially no
   `10.203.1.0/24` or `10.203.2.0/24`. If an old route is configured, clear it
   with `sudo tailscale set --advertise-routes=` and check both surfaces again.
3. Record `tailscale status --json` with peer names/addresses redacted in the
   shared evidence, plus `ip route show`. Prove management access to the Pi's
   Tailscale address from an authorized peer. A healthy local daemon alone does
   not prove the management path is reachable.
4. Run the lab only through its reviewed isolated container/namespace path.
   `lab/run_docker.sh` checks that its A→B→C namespaces have no default route
   and leave parent routes/rules unchanged. Capture the runner's evidence path;
   do not infer the Tailscale control-plane state from the lab result alone.
5. Close KAN-44 only after the device identity, reachable private management,
   empty advertised-route setting and admin-console route state, isolated lab
   result, and owner review are all recorded. A missing or unreadable check is
   incomplete evidence, not a pass.

Tailscale documents [client preferences](https://tailscale.com/docs/reference/tailscale-cli)
and the separate [subnet-router approval path](https://tailscale.com/kb/1104/enable-ip-forwarding).
Do not publish auth keys, unredacted peer inventories or credentials in Git/Jira.
