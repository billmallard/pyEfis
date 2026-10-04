#!/usr/bin/env bash
#  SPDX-License-Identifier: GPL-2.0-or-later
#
# bench-sweep -- report abandoned or synthetic state on a shared bench box.
#
# Both benches are multi-tenant (AVIONICS holds the Beelink key; AVIONICS, QA
# and AVIONICS-DATA hold the Pi's). A helper left running by a finished session
# is not merely untidy: AER-2663 found a pose injector that had been writing six
# keys into the FIX bus every 150 ms for SEVEN DAYS, with a 0-byte log. The bus
# has no source arbitration, so every visual observation taken from that glass
# in that week was of an injected pose, and nothing surfaced it.
#
# Three checks, in the order they matter:
#
#   1. FIX-bus clients   Is anything other than a known client connected to
#                        fix-gateway?  An unexpected client can pin the glass to
#                        a synthetic pose, so every observation taken while it
#                        runs is of that pose, not of the real source. This is
#                        the damage; run it before trusting any bench visual.
#   2. bench lock        Is the bench lock held, and by whom *really*?  An
#                        flock(2) lock lives on the open file description, not
#                        the process, so an orphaned child inherits it and
#                        /proc/locks keeps naming the dead parent. Reading that
#                        record alone makes an orphan look like a live holder --
#                        which is how AER-2663 read as "someone has the box" for
#                        a week. See bench_deploy.md: use `flock -o` whenever
#                        the locked command backgrounds anything.
#   3. stale scratch      Any process running out of the scratch directory for
#                        longer than the age threshold.
#
# Exit 0 clean, 1 findings reported, 2 usage error. REPORTS ONLY -- it never
# kills anything. A sweep that killed would eventually take out a legitimate
# long perf run or capture mid-flight and its owner would never learn why the
# evidence vanished; deciding to kill another agent's run is a human/owner call.
#
# Everything is read from /proc -- no ss(8), no ps(1). That is deliberate: the
# first draft of check 3 shelled out to `ps -eo ...`, and on a box without
# procps it printed "ok: no processes reference <scratch>" and exited 0. A
# detector that reports CLEAN when its instrument is missing is the same defect
# as the 0-byte log above, so neither check is allowed to depend on a tool that
# may not be installed. Requires: /proc, flock(1), awk, coreutils.
#
# Usage, as a precheck before trusting an observation:
#   ssh ... 'flock -o -w 900 /tmp/pyefis-bench.lock ~/pyEfis/tools/bench_sweep.sh'
# ...though the sweep is read-only and does not require the lock.
#
# Hourly on a bench: extras/extras/bench-sweep.service + .timer.

set -u

LOCK=/tmp/pyefis-bench.lock
SCRATCH="$HOME/bench-scratch"
MAX_AGE_S=3600
FIX_PORT=3490
# The two benches start pyEfis differently and BOTH spellings have to pass, or
# the sweep cries wolf hourly at the legitimate display. The Pi runs
# `.../python pyEfis.py`; the Beelink runs the installed console script
# `/home/pyefis/pyefis-venv/bin/pyefis` (verified on both, 2026-10-04).
# `bin/pyefis` is deliberately narrower than a bare `pyefis`: every path on the
# Beelink contains "pyefis" somewhere, including the venv interpreter that an
# injector would also be launched with.
FIX_ALLOW='fixgw|pyEfis\.py|bin/pyefis'
FINDINGS=0

usage() {
  cat >&2 <<EOF
usage: bench_sweep.sh [--lock PATH] [--scratch DIR] [--max-age SECONDS]
                      [--fix-port PORT] [--fix-allow EREGEX]

Reports abandoned or synthetic state on a shared bench. Never kills anything.
Exit 0 clean, 1 findings, 2 usage error.
EOF
  exit 2
}

die_usage() { echo "bench-sweep: $*" >&2; usage; }

# A non-numeric --max-age/--fix-port would surface much later as a confusing
# `[: integer expression expected`, mid-check, after some output. Fail now.
want_int() {
  case "$2" in
    '' | *[!0-9]*) die_usage "$1 needs a non-negative integer, got '$2'" ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --lock) LOCK="${2:-}"; [ -n "$LOCK" ] || die_usage "--lock needs a path"; shift 2 ;;
    --scratch) SCRATCH="${2:-}"; [ -n "$SCRATCH" ] || die_usage "--scratch needs a dir"; shift 2 ;;
    --max-age) want_int --max-age "${2:-}"; MAX_AGE_S="$2"; shift 2 ;;
    --fix-port) want_int --fix-port "${2:-}"; FIX_PORT="$2"; shift 2 ;;
    --fix-allow) FIX_ALLOW="${2:-}"; [ -n "$FIX_ALLOW" ] || die_usage "--fix-allow needs a regex"; shift 2 ;;
    -h|--help) usage ;;
    *) die_usage "unknown argument '$1'" ;;
  esac
done

finding() { FINDINGS=$((FINDINGS + 1)); echo "FINDING: $*"; }
ok()      { echo "ok: $*"; }

CLK_TCK=$(getconf CLK_TCK 2>/dev/null || echo 100)
UPTIME_S=$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || echo 0)

# /proc/<pid>/stat fields are positional, but field 2 is the comm in
# parentheses and a comm may contain spaces AND parentheses -- `(Web Content)`,
# `(sh) (odd)`. Splitting on whitespace shifts every later field. Everything
# after the LAST ')' is unambiguous, so parse from there: $1 there is state,
# $2 is ppid, $20 is starttime.
proc_stat_field() {  # proc_stat_field PID FIELD_AFTER_COMM
  awk -v want="$2" '{
    i = index($0, ")"); last = i
    while (i > 0) { j = index(substr($0, last + 1), ")"); if (j == 0) break; last += j }
    n = split(substr($0, last + 2), f, " ")
    if (want <= n) print f[want]
  }' "/proc/$1/stat" 2>/dev/null
}

proc_ppid() { proc_stat_field "$1" 2; }

# Age in whole seconds, from the kernel's own start time. Always available for
# a live pid, needs no external tool, and cannot silently return nothing the
# way `ps -o etimes=` does on a box with no procps.
proc_age_s() {
  local st
  st=$(proc_stat_field "$1" 20)
  case "$st" in '' | *[!0-9]*) return 1 ;; esac
  echo $(( UPTIME_S - st / CLK_TCK ))
}

fmt_age() {  # seconds -> 7d01h55m / 2h04m09s / 41s
  local s="$1"
  if   [ "$s" -ge 86400 ]; then printf '%dd%02dh%02dm' $((s/86400)) $((s%86400/3600)) $((s%3600/60))
  elif [ "$s" -ge 3600 ];  then printf '%dh%02dm%02ds' $((s/3600)) $((s%3600/60)) $((s%60))
  elif [ "$s" -ge 60 ];    then printf '%dm%02ds' $((s/60)) $((s%60))
  else printf '%ds' "$s"
  fi
}

proc_cmd() {
  local cmd
  # The subshell is load-bearing. `tr ... < file 2>/dev/null` suppresses tr's
  # stderr, but the INPUT REDIRECTION is performed by the shell, so when the
  # process exits between the /proc glob and this read the shell itself prints
  # "No such file or directory" to the report. Observed on the Pi, which has
  # ~400 processes turning over. Wrapping the redirect in a subshell whose
  # stderr is discarded is what actually silences the race.
  cmd=$( (tr '\0' ' ' < "/proc/$1/cmdline") 2>/dev/null )
  # A kernel thread (or a process that just died) has an empty cmdline; comm
  # at least names it rather than printing a bare pid with no clue.
  [ -n "$cmd" ] || cmd="[$(cat "/proc/$1/comm" 2>/dev/null)]"
  echo "$cmd"
}

# describe PID -> "pid 123 (up 7d01h55m) /path/to/cmd ...", rc=1 if gone.
# Appends ", PPID 1 -- reparented, nothing manages it" when the process has
# been orphaned: that is the tell from the AER-2663 root cause, and unlike the
# /proc/locks record it is readable even when the lock record is not.
describe() {
  local pid="$1" age shown extra=""
  [ -d "/proc/$pid" ] || return 1
  if age=$(proc_age_s "$pid"); then shown=$(fmt_age "$age"); else shown="unknown"; fi
  [ "$(proc_ppid "$pid")" = "1" ] && extra=", PPID 1 -- reparented, nothing manages it"
  echo "pid $pid (up ${shown}${extra}) $(proc_cmd "$pid")"
}

# Our own ancestry, so a check cannot report US as the problem. This is not
# cosmetic: the documented way to run the sweep is
# `ssh ... 'flock ... sh -c ".../bench_sweep.sh --scratch ~/bench-scratch"'`,
# which puts the scratch path into our own and our parents' argv -- check 3
# would otherwise find itself every single time it ran.
self_chain() {
  local pid="$$" guard=0
  while [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$guard" -lt 64 ]; do
    echo "$pid"
    pid=$(proc_ppid "$pid")
    guard=$((guard + 1))
  done
}
SELF_PIDS=" $(self_chain | tr '\n' ' ') "
is_self() { case "$SELF_PIDS" in *" $1 "*) return 0 ;; esac; return 1; }

# One pass over every readable fd on the box -> "pid<TAB>target" lines. Both
# check 1 (socket inode -> pid) and check 2 (lock path -> pid) are answered
# from this single snapshot.
FD_MAP=$(
  for d in /proc/[0-9]*; do
    pid="${d#/proc/}"
    for f in "$d"/fd/*; do
      link=$(readlink "$f" 2>/dev/null) || continue
      printf '%s\t%s\n' "$pid" "$link"
    done
  done
)

fd_holders() {  # live pids holding an open fd on path $1, however inherited
  printf '%s\n' "$FD_MAP" | awk -F'\t' -v t="$1" '$2 == t { print $1 }' | sort -un
}

socket_pid() {  # pid holding socket inode $1
  printf '%s\n' "$FD_MAP" | awk -F'\t' -v t="socket:[$1]" '$2 == t { print $1 }' | head -1
}

# pids recorded against inode $1 in /proc/locks, holders only.
#
# Two format notes. A record is `1: FLOCK ADVISORY WRITE <pid> <maj:min:ino> ...`,
# but a blocked WAITER is printed as `1: -> FLOCK ADVISORY WRITE <pid> ...` --
# same fields shifted right by one. Scanning for the field that looks like
# maj:min:ino and taking the one before it reads the pid correctly in both
# forms; and skipping the `->` lines keeps a colleague who is merely queued in
# `flock -w 900` from being reported as a holder.
lock_record_pids() {
  awk -v ino="$1" '
    $2 == "->" { next }
    { for (f = 1; f <= NF; f++)
        if ($f ~ "^[0-9a-f]+:[0-9a-f]+:" ino "$") print $(f - 1) }
  ' /proc/locks 2>/dev/null | sort -un
}

echo "bench-sweep $(date -u '+%Y-%m-%dT%H:%M:%SZ') on $(hostname 2>/dev/null || cat /proc/sys/kernel/hostname)"
if [ "$(id -u)" != "0" ]; then
  # Not a finding -- just the honest reach of this run. fds and cmdlines of
  # another user's processes are unreadable, so a holder or an injector owned
  # by someone else can only be reported as "unresolved", never named.
  echo "note: running as $(id -un), not root -- processes owned by other users"
  echo "      cannot be resolved to a pid. Re-run with sudo to see the whole box."
fi
echo

# ---- 1. FIX-bus clients ---------------------------------------------------
echo "[1] clients connected to the FIX bus (port $FIX_PORT)"
fix_hex=$(printf '%04X' "$FIX_PORT")
# /proc/net/tcp{,6}: $2/$3 are hex addr:port, $4 is the state (01 =
# ESTABLISHED), $10 is the socket inode. The header row has $4 == "st" and so
# never matches. Both families, because fixgw may bind either.
fix_inodes=$(awk -v p="$fix_hex" '
  $4 == "01" {
    split($2, l, ":"); split($3, r, ":")
    if (toupper(l[2]) == p || toupper(r[2]) == p) print $10
  }' /proc/net/tcp /proc/net/tcp6 2>/dev/null | sort -un)

if [ -z "$fix_inodes" ]; then
  # Not automatically good: on a bench that is meant to be displaying, no
  # client at all means pyEfis is not talking to fixgw. Report it plainly and
  # let the reader judge -- the sweep does not know the intent.
  ok "no established connections on port $FIX_PORT (nothing is driving the glass)"
else
  seen=""
  while read -r ino; do
    [ -n "$ino" ] || continue
    pid=$(socket_pid "$ino")
    if [ -z "$pid" ]; then
      finding "established FIX-bus socket (inode $ino) belongs to a process this" \
              "run cannot read -- an unresolved client may be driving the glass"
      continue
    fi
    # One client holds two sockets when both ends are local; report it once.
    case " $seen " in *" $pid "*) continue ;; esac
    seen="$seen $pid"
    desc=$(describe "$pid") || continue
    if echo "$desc" | grep -Eq "$FIX_ALLOW"; then
      ok "expected FIX client: $desc"
    else
      finding "unexpected process on the FIX bus -- it may be driving the glass: $desc"
    fi
  done < <(printf '%s\n' "$fix_inodes")
fi
echo

# ---- 2. bench lock --------------------------------------------------------
echo "[2] bench lock $LOCK"
lock_state=0   # 0 free, 1 held, 2 cannot open -- read again by the holder-record check
lock_probe() {  # 0 = free (taken and released), 1 = held, 2 = cannot open
  # Do NOT hand the path to flock(1). It opens O_RDONLY|O_CREAT, and O_CREAT on
  # a file you do not own in a sticky world-writable directory is refused by
  # fs.protected_regular -- **including for root**. On the Beelink the lock is
  # /tmp/pyefis-bench.lock owned by `pyefis`, so a root sweep got EACCES and the
  # first version of this check reported that as "the lock is HELD", a false
  # finding that would have fired every hour under the system unit.
  #
  # Opening read-only ourselves and locking the FD avoids it: O_RDONLY is not
  # gated, and flock(2) takes an exclusive lock on a read-only fd perfectly
  # well. The subshell means a failed redirect cannot take down the sweep, and
  # closing the fd on subshell exit is what releases the probe lock.
  ( : < "$1" ) 2>/dev/null || return 2
  if ( exec 9<"$1"; flock -n 9 ) 2>/dev/null; then return 0; fi
  return 1
}

if [ ! -e "$LOCK" ]; then
  ok "lock file does not exist (nothing holds the bench)"
else
  ino=$(stat -c %i "$LOCK" 2>/dev/null)
  lock_probe "$LOCK"
  lock_state=$?
  if [ "$lock_state" -eq 2 ]; then
    finding "cannot open lock file $LOCK as $(id -un) -- holder undeterminable." \
            "Not the same thing as held: check ownership/permissions, and note that" \
            "fs.protected_regular denies even root an O_CREAT open here."
  elif [ "$lock_state" -eq 0 ]; then
    ok "lock is free"
    # A record on a lock we just took means our own view is wrong; worth saying.
    if [ -n "$ino" ] && [ -n "$(lock_record_pids "$ino")" ]; then
      finding "lock reports free but /proc/locks still carries a holder record for inode $ino"
    fi
  else
    rec_pids=$(lock_record_pids "$ino")
    true_pids=$(fd_holders "$LOCK")

    echo "    recorded in /proc/locks:$(printf ' %s' ${rec_pids:-none})"
    echo "    actually holding an fd :$(printf ' %s' ${true_pids:-none})"

    dead_rec=""
    for p in $rec_pids; do [ -d "/proc/$p" ] || dead_rec="$dead_rec $p"; done

    if [ -n "$dead_rec" ]; then
      finding "lock is HELD but its /proc/locks record names dead pid(s)${dead_rec} --" \
              "an orphan inherited the open file description; the record is not the holder"
    fi

    # The orphan has a second face. A dead pid cannot be translated into the
    # reader's pid namespace, so in a container the record does not name a
    # corpse -- it DISAPPEARS, leaving a held lock with no record at all
    # (reproduced locally; the Pi, outside any namespace, shows the corpse
    # instead). Same condition, so catch it the same way: the record fails to
    # account for anyone who actually holds an fd. A legitimate holder always
    # overlaps -- it took the lock itself, and a child that inherited the fd
    # leaves the taker in the record alongside it.
    if [ -n "$true_pids" ]; then
      overlap=0
      for p in $true_pids; do
        for r in $rec_pids; do [ "$p" = "$r" ] && overlap=1; done
      done
      if [ "$overlap" -eq 0 ] && [ -z "$dead_rec" ]; then
        finding "lock is HELD but no /proc/locks record names any process that actually" \
                "holds it -- the taker is gone and an orphan inherited the open file" \
                "description (see bench_deploy.md: use \`flock -o\`)"
      fi
    fi

    if [ -z "$true_pids" ]; then
      finding "lock is HELD and no readable process holds an fd on it (holder may be another user)"
    else
      for p in $true_pids; do
        desc=$(describe "$p") || continue
        age=$(proc_age_s "$p") || age=""
        if [ -n "$age" ] && [ "$age" -gt "$MAX_AGE_S" ]; then
          finding "bench lock held for $(fmt_age "$age") (> ${MAX_AGE_S}s) by $desc"
        else
          ok "lock held by $desc"
        fi
      done
    fi
  fi
fi

# The holder record bench-deploy.sh writes next to the lock (owner=, issue=,
# pid=, since=). It is the only thing on the box that names WHO claims the
# bench, so it is worth reading even when the lock itself is free -- and worth
# distrusting, because it is a plain file that nothing clears. Checking the
# liveness of the pid it names is the whole point: a record naming a dead pid
# from seven days ago is exactly what read as "someone is working" in AER-2663.
#
# A dead pid is only a FINDING while the lock is held (or undeterminable):
# that is the AER-2663 shape, a live claim with nobody behind it. With the lock
# free it is ordinary residue -- bench-deploy.sh writes the record on every run,
# --check included, and never removes it -- so flagging it there made the first
# timer-driven sweep after any deploy report the bench dirty (AER-2666).
if [ -r "$LOCK.owner" ]; then
  echo "    holder record $LOCK.owner:"
  sed 's/^/      /' "$LOCK.owner" 2>/dev/null | head -5
  rec_owner_pid=$(sed -n 's/.*[[:space:]]pid=\([0-9]\{1,\}\).*/\1/p;s/^pid=\([0-9]\{1,\}\).*/\1/p' \
                    "$LOCK.owner" 2>/dev/null | head -1)
  if [ -n "$rec_owner_pid" ] && [ ! -d "/proc/$rec_owner_pid" ]; then
    if [ "$lock_state" -eq 0 ]; then
      ok "holder record names pid $rec_owner_pid, which is not running -- residue of a finished run (the lock is free)"
    else
      finding "the holder record claims the bench for pid $rec_owner_pid, which is NOT running --" \
              "treat the claim as expired, not as a colleague at work"
    fi
  fi
fi
echo

# ---- 3. stale scratch processes -------------------------------------------
echo "[3] processes running out of $SCRATCH older than ${MAX_AGE_S}s"
found_scratch=0
for d in /proc/[0-9]*; do
  pid="${d#/proc/}"
  is_self "$pid" && continue
  # Subshell for the same reason as proc_cmd above: a process that exits
  # mid-scan must not put a shell error into the report.
  args=$( (tr '\0' ' ' < "$d/cmdline") 2>/dev/null ) || continue
  case "$args" in
    *"$SCRATCH"*) ;;
    *) continue ;;
  esac
  found_scratch=1
  age=$(proc_age_s "$pid") || age=0
  if [ "$age" -gt "$MAX_AGE_S" ]; then
    finding "scratch process running $(fmt_age "$age") (> ${MAX_AGE_S}s): $(describe "$pid")"
  else
    ok "scratch process $(describe "$pid")"
  fi
done
[ "$found_scratch" = 0 ] && ok "no processes reference $SCRATCH"
echo

if [ "$FINDINGS" -gt 0 ]; then
  echo "bench-sweep: $FINDINGS finding(s). The bench is not in a clean state --"
  echo "do not trust an observation taken from it until these are resolved."
  exit 1
fi
echo "bench-sweep: clean."
exit 0
