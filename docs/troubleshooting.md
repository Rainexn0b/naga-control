# Troubleshooting

## Service says `absent` or mappings do nothing

1. Check the receiver/cable: `busctl --user call org.nagacontrol.Service1
   /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot` — `status`
   must be `available`.
2. Verify OpenRazer sees the device: `python -c "from openrazer.client import
   DeviceManager; print([d.name for d in DeviceManager().devices])"`. If the
   Naga V3 Pro is missing, the required OpenRazer baseline (see
   `docs/release-notes.md`) is not installed and the openrazer daemon needs
   restarting.
3. Driver mode regression: if clicks work but mapped buttons (DPI buttons,
   side grid) do nothing, the mouse regressed to mode `0:0`. Restart the
   service (it reasserts `3:0`) or cycle the mouse power switch.

## Startup fails with "physical keys are held before grab"

A release event was lost earlier and the kernel still reports a pressed key.
Tap the affected button (usually the one last held, e.g. a side button or
left click) once; restart the service. The journal names the node.

## Mapped buttons emit digits instead of their mapping

The active profile's bindings are the defaults. Open the GUI Buttons page
and apply the desired bindings, or select another profile on the Profiles
page.

## Inputs behave oddly while another remapper runs

Input Remapper and similar tools race for the same evdev nodes. Stop them:
`systemctl --user stop input-remapper.service`.

## Debug bundle

Collect a sanitized diagnostic capture with:

```bash
naga-control-capture --help   # from a pip install; or:
./dist/Naga-Control-*.AppImage capture --help
```

Captures redact serial numbers and identifiers before writing; see the
`REDACTED` handling in `src/naga_control/diagnostics/capture.py`. For
service logs use `journalctl --user -u naga-control.service -b`.

## Emergency release

If generated keys stick, press the GUI "Release generated outputs" button or
run `busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1
org.nagacontrol.Service1 ReleaseAll`. Unplugging the receiver also releases
everything; SIGKILL drops all grabs via the kernel.
