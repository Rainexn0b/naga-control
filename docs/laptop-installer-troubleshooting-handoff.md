# Laptop Installer Troubleshooting Handoff

Date: 2026-10-11. Standalone handoff for the laptop session.

Read this with [AGENTS](../AGENTS.md) plus the five required docs before
changing product code: [starter](naga-linux-control-agent-starter.md),
[findings](integration-findings.md), [architecture](architecture.md),
[plan](implementation-plan.md), and [validation](hardware-validation.md).
Installer behavior is defined in [release-notes](release-notes.md) and
[troubleshooting](troubleshooting.md); this file adds no new installer behavior.

## Status

Laptop install did NOT finish. Verified v0.5.0 image bytes were
reused and no image replacement happened. Package and group changes
below persist; do not silently roll them back.

Two open issues remain distinct and must stay separate:

1. DKMS build failure on the running kernel, cause unknown.
2. Naga service reactivation abort before image replacement,
   trigger and post-exit service state UNKNOWN.

## Laptop runtime evidence

Host: CachyOS x86_64. Running kernel 7.2.9-2-cachyos; other
installed kernel 6.18.55-2-cachyos-lts.

Accepted package evidence:

- Separate DKMS consent offer succeeded: dkms 3.4.3-1 installed.
- Read-only active-kernel preflight then passed.
- `pacman -U` installed the full local cohort
  3.12.1.pr2904.fix2-1 at authoritative source SHA
  26b0eeb5ed70d638fa3528851adcd5e58369a7f5.
- Package hook for 7.2.9-2-cachyos ran:
  `dkms install --no-depmod openrazer-driver/3.12.1.pr2904.fix2 -k 7.2.9-2-cachyos`
  and the DKMS hook reported exit 10.
- Do NOT invent a cause: missing headers, compiler mismatch, and
  kernel API breakage are all unproven.
- Same hook for 6.18.55-2-cachyos-lts showed success plus depmod.
  That is package-hook evidence only, NOT module-loaded, support
  verified, or hardware acceptance.
- User separately consented openrazer group addition; effective
  session membership is unverified until relogin.
- Helper enabled per-user openrazer-daemon.service without --now;
  explicit activation was deferred. Helper did no explicit live
  module or daemon restart. Package-manager hooks may normally
  have reloaded user and device managers.
- Installer stopped Naga after consent, later detected Naga active
  again, and aborted BEFORE replacing the image. Open GUI or D-Bus
  reactivation is a hypothesis only. Cleanup text saying
  `Naga remains stopped` is not readback proof.

## Accepted code evidence, not laptop runtime

- Same curl command on current main has the DKMS offer verified
  live at 8469ce7; prior e67aac4 published normal and native setup and
  remote UI 1b344b1 preserved by merge 0822dff are in that tree.
- Source CI passed Python 3.12:
  https://github.com/Rainexn0b/naga-control/actions/runs/38137624027
- Local independent checks: ruff, ruff format, pyright, compile,
  bash syntax, shellcheck, pytest with 4057 passed, 2
  coverage-skipped, 5 hardware-deselected.
- These prove source and fake health only, not laptop runtime.
- Published v0.5.0 is unchanged, so source UI additions are NOT
  newly shipped AppImage bytes.
- OpenRazer aliases being synced, SHA and cohort unchanged:
  branch naga-v3-pro-compat and tag naga-v3-pro-compat-v1,
  formerly test-pr-2904-edualb; legacy naga-v3-pro-legacy.
  Parent verified branch and tag peeled hashes resolve to the
  full SHA above; no new release or retag is claimed.

## Pending diagnostics, not yet collected

No further live operations were authorized or run by the parent.
Collect these first on the laptop, in order:

```bash
dkms status
sudo tail -n 150 /var/lib/dkms/openrazer-driver/3.12.1.pr2904.fix2/build/make.log
systemctl --user show naga-control.service -p ActiveState -p SubState -p Result
journalctl --user -u naga-control.service -n 50 --no-pager
```

Notes: build/make.log may have been overwritten by the later LTS
build, so verify which kernel the log describes before diagnosing.
Redact serials, port paths, and other identifiers before sharing.
A GetSnapshot or busctl call can D-Bus activate Naga, so it is not
a passive-state check; treat service state and activation separately.

## Next safe steps

1. Pull latest main ONLY if the working tree is clean. Run
   `git status` first; do not reset, stash, or discard the other
   session's changes.
2. Quit the GUI before any consented service or integration change.
3. Investigate the module build failure from the correct kernel
   log first (compiler cause unknown); do not skip to
   reinstallation or activation.
4. A temporary boot into the already installed LTS kernel is an
   operator decision to offer only, not an automatic kernel
   upgrade, migration, or activation.
5. Do not blindly re-run --install-openrazer now that a backend is
   present; on Arch that flag reinstalls the whole cohort.
6. After prerequisites are validated and separate service-stop
   consent is obtained, an ordinary app-only rerun can complete
   integration. It does not repair the failed DKMS build on the
   current kernel.

## Non-goals

- No raw HID, no Qt boundary changes, only 1532:00E7 and 1532:00E8.
- Keep all Python files at or below 400 physical lines; keep USB
  ancestor identity, forwarding-before-grab, held-action cleanup,
  and milestone order unchanged.
- No unattended hardware tests, no service or GUI as root, no
  source pin change, migration, deployment, or release without
  explicit approval.
- This handoff does not authorize package changes, live activation,
  device access, kernel/source migrations, or releases. Follow
  AGENTS.md and current agent routing and obtain operator consent
  for state-changing troubleshooting.
