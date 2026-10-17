# Evdev Callback Investigation, 2026-10-17

Bounded adapter fix for the confirmed async cancellation race. Scoped manual
startup/reconnect acceptance on the local 0.5.1 HyperSpeed candidate is
recorded in [hardware validation](hardware-validation.md#manual-051-candidate-acceptance-2026-10-17-hyperspeed-12-button);
CI/tag pipeline verification remains with the parent. No release or deployment
was performed by the worker.

## Proof

- Fake-only proof uses the actual upstream `ReadIterator` with a fake fd
  contract plus the real `EvdevSource`/`SourceReader` path, no device nodes.
- Cancel-first then completing the inner future with the lazy read generator
  lets task teardown close before the queued `next_batch_ready` callback
  consumes the batch. The lazy read raises `EBADF`, then `set_exception`
  on the cancelled outer raises `InvalidStateError`, sent to the loop
  exception handler.
- Selector nuance: `remove_reader` cancels a queued selector handle but
  cannot retract an already-queued future done-callback. The rejected
  tracking-guard approach that tracks pending upstream futures leaks when
  close drops readiness. This proves only that rejected approach leaks; it
  does not prove all upstream guards leak and does not identify the historical
  initiator.

## Fix

- New `src/naga_control/adapters/evdev/async_reader.py` owns one
  `loop.add_reader` registration per source. The callback only signals an
  owned `asyncio.Event`; `device.read` runs in the reading coroutine.
- Exactly one active iterator, no task per event, no pending futures.
  Detach retires with the stored fd/loop token before `device.close`,
  stays idempotent, keeps stale callbacks benign, and never removes a
  fresh registration after fd reuse.
- `src/naga_control/adapters/evdev/source.py` delegates to the owned
  iterator using only `fd`/`read`. Intentional close/cancel ends cleanly
  without manufacturing `EBADF`; genuine `EBADF`/`EIO`/`ENODEV` still
  propagate with exact identity.
- Lazy `EAGAIN` from `next()` rearms like immediate `EAGAIN`, never EOF;
  other lazy errors keep identity. First detach failure is cached and
  surfaced through close/stop while the primary is preserved.

## Gates

- RED before fix: `tests/test_evdev_cancel_race.py` cancel-first fails
  with exit 1 and `InvalidStateError` handler noise; readiness-first stays
  silent. Lazy `EAGAIN` RED fails with `BlockingIOError` ending the stream;
  detach RED shows clean close instead of the cached `remove` identity.
  GREEN after fix parks on `EAGAIN`, delivers later batches, and preserves
  first detach identity with no extra syscalls on retry.
- Focused gate passes: async reader, lazy, close, cancel race, source
  adapter, source, removal, reader, session/service failures, cleanup
  barriers, first slice, state poll, and frame planner. `ruff check`,
  `ruff format --check`, and `pyright` pass. All Python files stay
  within 400 physical lines.

## Manual acceptance and still-open gates

- Scoped manual startup and receiver reconnect acceptance on the local 0.5.1
  HyperSpeed candidate passed with F17 holds/releases plus pointer, click,
  scroll, and move and no `InvalidStateError`/`EBADF` burst; exact latency was
  not measured. See [hardware validation](hardware-validation.md#manual-051-candidate-acceptance-2026-10-17-hyperspeed-12-button).
  This proves the adapter-owned fix avoids the confirmed race; it does not
  prove the historical initiator.
- Reconnect latency and natural idle/wake checks remain open.
- CI/tag pipeline verification remains with the parent after commit/push/CI/tag.
- See [architecture](architecture.md),
  [hardware validation](hardware-validation.md),
  [implementation plan](implementation-plan.md), and
  [F17 receipt](f17-investigation-2026-10-17.md).
