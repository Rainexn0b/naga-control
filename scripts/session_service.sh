#!/usr/bin/env bash
# Naga Control session-bus service helper (non-systemd mode).
# Sourceable into installers: defining only naga_session_* functions is the
# entire source-time effect. No option changes, traps, or executions on source.
# Future installed path (informational only): ~/.local/share/naga-control/session-service.sh
# Session D-Bus contract (fixed):
#   bus and interface: org.nagacontrol.Service1
#   object: /org/nagacontrol/Service1
#   PrepareShutdown (no args, no result): closes the application gate and awaits
#     clean shutdown while keeping the bus name; successful reply only on success.
#   Exit (no args, no result): allowed only after successful PrepareShutdown;
#     may disconnect before its reply, so the caller tolerates a missing reply
#     only after successful PrepareShutdown and verifies name loss.
# Only dbus-send --session with a bounded --reply-timeout and only the fixed
# broker/service methods below are used. dbus-send and sleep are the explicit
# session-mode tool requirements; busctl, systemctl, python, AppImage, pgrep,
# pkill, killall, kill, or PID signalling are never used.

# Fail closed before any dbus-send when no explicit session address exists or
# when the address could autolaunch a new bus. Explicit addresses are left to
# dbus-send; no fallback to system bus, X11, or autolaunch is attempted.
naga_session__check_bus_address() {
  local address="${DBUS_SESSION_BUS_ADDRESS:-}"
  if [ -z "$address" ]; then
    printf 'error: session bus is not available\n' >&2
    return 1
  fi
  case "$address" in
    *autolaunch:*)
      printf 'error: session bus is not available\n' >&2
      return 1
      ;;
  esac
  return 0
}

naga_session__check_tools() {
  if ! command -v dbus-send >/dev/null 2>&1; then
    printf 'error: session service tools are not available\n' >&2
    return 1
  fi
  if ! command -v sleep >/dev/null 2>&1; then
    printf 'error: session service tools are not available\n' >&2
    return 1
  fi
  if ! naga_session__check_bus_address; then
    return 1
  fi
  return 0
}

naga_session_bus_check() {
  local output=""
  local reply_timeout="10000"
  if ! naga_session__check_tools; then
    return 1
  fi
  if ! output="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetId 2>/dev/null 9>&-)"; then
    printf 'error: session bus is not available\n' >&2
    return 1
  fi
  case "$output" in
    *'string "'*)
      printf 'ready\n'
      return 0
      ;;
    *)
      printf 'error: session bus is not available\n' >&2
      return 1
      ;;
  esac
}

naga_session_status() {
  local output=""
  local reply_timeout="10000"
  if ! naga_session__check_tools; then
    return 1
  fi
  if ! output="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.nagacontrol.Service1 2>/dev/null 9>&-)"; then
    printf 'error: service status is unknown\n' >&2
    return 1
  fi
  case "$output" in
    *'boolean true'*)
      printf 'active\n'
      return 0
      ;;
    *'boolean false'*)
      printf 'inactive\n'
      return 0
      ;;
    *)
      printf 'error: service status is unknown\n' >&2
      return 1
      ;;
  esac
}

naga_session_start() {
  local output=""
  local reply_timeout="10000"
  local poll_interval="0.2"
  local attempts="25"
  if ! naga_session__check_tools; then
    return 1
  fi
  if ! dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.StartServiceByName string:org.nagacontrol.Service1 uint32:0 >/dev/null 2>&1 9>&-; then
    printf 'error: service start failed\n' >&2
    return 1
  fi
  while [ "$attempts" -gt 0 ]; do
    if output="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.nagacontrol.Service1 2>/dev/null 9>&-)"; then
      case "$output" in
        *'boolean true'*)
          printf 'active\n'
          return 0
          ;;
      esac
    fi
    sleep "$poll_interval" >/dev/null 2>&1 9>&- || true
    attempts=$((attempts - 1))
  done
  printf 'error: service start timed out\n' >&2
  return 1
}

naga_session_stop() {
  local output=""
  local owner_output=""
  local unique=""
  local reply_timeout="10000"
  local poll_interval="0.2"
  local attempts="25"
  local unique_pattern='string "(:[0-9]+\.[0-9]+)"'
  local strict_pattern='^:[0-9]+\.[0-9]+$'
  local poll_unique=""
  local poll_well=""
  local poll_unique_rc="1"
  local poll_well_rc="1"
  if ! naga_session__check_tools; then
    return 1
  fi
  if ! output="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.nagacontrol.Service1 2>/dev/null 9>&-)"; then
    printf 'error: service status is unknown\n' >&2
    return 1
  fi
  case "$output" in
    *'boolean false'*)
      printf 'inactive\n'
      return 0
      ;;
    *'boolean true'*)
      ;;
    *)
      printf 'error: service status is unknown\n' >&2
      return 1
      ;;
  esac
  if ! owner_output="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetNameOwner string:org.nagacontrol.Service1 2>/dev/null 9>&-)"; then
    printf 'error: service stop failed\n' >&2
    return 1
  fi
  if [[ $owner_output =~ $unique_pattern ]]; then
    unique="${BASH_REMATCH[1]}"
  else
    printf 'error: service stop failed\n' >&2
    return 1
  fi
  if [[ ! $unique =~ $strict_pattern ]]; then
    printf 'error: service stop failed\n' >&2
    return 1
  fi
  if ! dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest="$unique" /org/nagacontrol/Service1 org.nagacontrol.Service1.PrepareShutdown >/dev/null 2>&1 9>&-; then
    printf 'error: service prepare failed\n' >&2
    return 1
  fi
  dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest="$unique" /org/nagacontrol/Service1 org.nagacontrol.Service1.Exit >/dev/null 2>&1 9>&- || true
  attempts="25"
  while [ "$attempts" -gt 0 ]; do
    poll_unique=""
    poll_well=""
    poll_unique_rc="1"
    poll_well_rc="1"
    if poll_unique="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:"$unique" 2>/dev/null 9>&-)"; then
      poll_unique_rc="0"
    fi
    if poll_well="$(dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.nagacontrol.Service1 2>/dev/null 9>&-)"; then
      poll_well_rc="0"
    fi
    if [ "$poll_unique_rc" = "0" ] && [ "$poll_well_rc" = "0" ]; then
      case "$poll_unique" in
        *'boolean false'*)
          case "$poll_well" in
            *'boolean false'*)
              printf 'inactive\n'
              return 0
              ;;
          esac
          ;;
      esac
    fi
    sleep "$poll_interval" >/dev/null 2>&1 9>&- || true
    attempts=$((attempts - 1))
  done
  printf 'error: service stop timed out\n' >&2
  return 1
}

naga_session_restart() {
  if ! naga_session_stop >/dev/null; then
    return 1
  fi
  # The verified stop above suppressed its inactive line; start prints active.
  naga_session_start
}

naga_session_reload() {
  local reply_timeout="10000"
  if ! naga_session__check_tools; then
    return 1
  fi
  if ! dbus-send --session --print-reply --reply-timeout="$reply_timeout" --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ReloadConfig >/dev/null 2>&1 9>&-; then
    printf 'error: session bus reload failed\n' >&2
    return 1
  fi
  printf 'reloaded\n'
  return 0
}

naga_session_main() {
  local cmd="${1:-}"
  case "$cmd" in
    bus-check)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_bus_check
      ;;
    status)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_status
      ;;
    start)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_start
      ;;
    stop)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_stop
      ;;
    restart)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_restart
      ;;
    reload)
      shift || true
      if [ "$#" -ne 0 ]; then
        printf 'error: unknown command\n' >&2
        return 2
      fi
      naga_session_reload
      ;;
    ""|-h|--help|help)
      printf 'usage: bash session_service.sh bus-check|status|start|stop|restart|reload\n' >&2
      return 2
      ;;
    *)
      printf 'error: unknown command\n' >&2
      return 2
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  naga_session_main "$@"
fi
