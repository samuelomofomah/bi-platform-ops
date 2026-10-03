#!/usr/bin/env bash
# Host-level health check for a BI server node (Tableau Server or a
# MicroStrategy Intelligence Server). Run it from cron, a Jenkins agent or a
# self-hosted GitHub runner on the box. Exits 1 if any check FAILs.
#
#   DISK_MAX=85 MEM_MAX=90 MOUNTS="/ /var/opt/tableau" SERVICES="sshd chronyd" ./linux_health.sh
set -uo pipefail

DISK_MAX=${DISK_MAX:-85}     # % used per mount
MEM_MAX=${MEM_MAX:-90}       # % of RAM in use
MOUNTS=${MOUNTS:-/}
SERVICES=${SERVICES:-}       # systemd units that must be active
failed=0

report() {  # report LEVEL CHECK MESSAGE
  printf '%-4s  %-24s %s\n' "$1" "$2" "$3"
  if [[ $1 == FAIL ]]; then failed=1; fi
}

# Disk
for mount in $MOUNTS; do
  used=$(df -P "$mount" 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $5}')
  if [[ -z $used ]]; then report FAIL "disk:$mount" "mount not found"
  elif (( used >= DISK_MAX )); then report FAIL "disk:$mount" "${used}% used (limit ${DISK_MAX}%)"
  else report OK "disk:$mount" "${used}% used"; fi
done

# Memory (uses MemAvailable, so page cache is not counted as pressure)
mem=$(awk '/^MemTotal/ {t=$2} /^MemAvailable/ {a=$2} END {printf "%d", (t - a) * 100 / t}' /proc/meminfo)
if (( mem >= MEM_MAX )); then report FAIL memory "${mem}% in use (limit ${MEM_MAX}%)"
else report OK memory "${mem}% in use"; fi

# Load: 5-minute average above the core count means the box is saturated
cores=$(nproc)
load5=$(awk '{print $2}' /proc/loadavg)
if awk -v l="$load5" -v c="$cores" 'BEGIN {exit !(l > c)}'; then report FAIL load "load5 ${load5} on ${cores} cores"
else report OK load "load5 ${load5} on ${cores} cores"; fi

# Services
for svc in $SERVICES; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then report OK "service:$svc" active
  else report FAIL "service:$svc" "not active"; fi
done

# Tableau Server processes, when this node runs TSM
if command -v tsm >/dev/null 2>&1; then
  status=$(tsm status 2>&1 | head -n 1)
  if [[ $status == *RUNNING* ]]; then report OK tableau_tsm "$status"; else report FAIL tableau_tsm "$status"; fi
fi

# Pending OS patches: a warning for the patching backlog, not a failure
if command -v dnf >/dev/null 2>&1; then
  pending=$(dnf -q check-update 2>/dev/null | grep -c '^[[:alnum:]]')
elif command -v apt-get >/dev/null 2>&1; then
  pending=$(apt list --upgradable 2>/dev/null | grep -c upgradable)
else
  pending=unknown
fi
if [[ $pending == 0 ]]; then report OK os_patches "up to date"; else report WARN os_patches "${pending} package(s) pending"; fi

exit "$failed"
