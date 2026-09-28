# Implementation Handoff

Read these files before changing product code:

1. `docs/naga-linux-control-agent-starter.md`
2. `docs/integration-findings.md`
3. `docs/architecture.md`
4. `docs/implementation-plan.md`
5. `docs/hardware-validation.md`

## Non-Negotiable Constraints

- Support only Razer Naga V3 Pro `1532:00E7` and `1532:00E8` in v0.1.
- Use OpenRazer for hardware operations. Do not add raw HID commands.
- Keep Qt outside domain, service, and hardware adapter modules.
- Keep all Python files at or below 400 physical lines.
- Keep the evdev read and forwarding path free of filesystem, GUI, and blocking
  OpenRazer calls.
- Never discover input devices by `eventN`, display name, or a virtual-device
  name alone. Require a matching physical USB ancestor.
- Never grab an evdev node before its forwarding uinput device is ready.
- On an unsafe state or write failure, release grabs and generated held keys.
- Resolve a mapping on key-down and retain that action until key-up, even if the
  active profile changes while the key is held.
- Do not run the GUI or service as root.
- Do not copy code from Polychromatic or Input Remapper.

## Delivery Order

Implement milestones in `docs/implementation-plan.md` in order. Do not begin
the full GUI before both first-slice event paths work with fakes and on hardware:

```text
F13/F14 -> action dispatcher -> OpenRazer DPI stage change
F17 down/up -> uinput KEY_LEFTALT down/up
```

## Standard Checks

```bash
ruff check .
ruff format --check .
pyright
pytest
```

Hardware tests are opt-in and must be marked `hardware`. Default tests must not
read, grab, or write real device nodes.
