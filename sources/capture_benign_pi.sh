#!/usr/bin/env bash
# KAN-66: one-hour benign Raspberry Pi capture with scenario/provenance evidence.
set -Eeuo pipefail

OUT=${1:?usage: capture_benign_pi.sh OUT_DIR [DURATION_SECONDS]}
DURATION=${2:-3600}
IFACE=${OMNIGUARD_CAPTURE_IFACE:-wlan0}
mkdir -p "$OUT"
OUT=$(cd -- "$OUT" && pwd)

if (( DURATION < 3600 )); then
    echo "duration must be at least one device-hour" >&2
    exit 2
fi
command -v tcpdump >/dev/null
command -v python3 >/dev/null

START_UTC=$(date --utc +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)
MODEL=$(tr -d '\0' </proc/device-tree/model)
KERNEL=$(uname -srmo)
ADDRESS=$(ip -brief address show "$IFACE" | tr -s ' ')
DEVICE_IPV4=$(ip -o -4 address show dev "$IFACE" scope global | awk 'NR == 1 {sub(/\/.*/, "", $4); print $4}')
if [[ -z "$DEVICE_IPV4" ]]; then
    echo "interface has no global IPv4 address" >&2
    exit 2
fi
CAPTURE_FILTER="host $DEVICE_IPV4"
THROTTLED_BEFORE=$(vcgencmd get_throttled 2>/dev/null || true)
TEMP_BEFORE=$(vcgencmd measure_temp 2>/dev/null || true)
LOAD_BEFORE=$(cat /proc/loadavg)

printf '%s\t%s\n' "$START_EPOCH" "idle-start" >"$OUT/scenarios.tsv"
sudo timeout --preserve-status --signal=INT "$DURATION" tcpdump -i "$IFACE" -s 0 -U \
    -w "$OUT/benign-pi5.pcap" "$CAPTURE_FILTER" >"$OUT/tcpdump.log" 2>&1 &
CAPTURE_PID=$!

(
    sleep 600
    printf '%s\t%s\n' "$(date +%s)" "dns-https-start"
    for host in deb.debian.org www.raspberrypi.com pkgs.tailscale.com; do
        getent ahosts "$host" >/dev/null || true
        curl --fail --silent --show-error --location --max-time 30 \
            "https://$host/" -o /dev/null || true
    done
    printf '%s\t%s\n' "$(date +%s)" "dns-https-end"
    sleep 300
    printf '%s\t%s\n' "$(date +%s)" "download-start"
    curl --fail --silent --show-error --location --max-time 600 \
        https://speed.hetzner.de/100MB.bin -o /dev/null || true
    printf '%s\t%s\n' "$(date +%s)" "download-end"
    printf '%s\t%s\n' "$(date +%s)" "idle-remainder"
    printf '%s\t%s\n' "$(date +%s)" "reconnect-not-run"
    printf '%s\t%s\n' "$(date +%s)" "update-not-run"
) >>"$OUT/scenarios.tsv" 2>>"$OUT/activity-errors.log" &
ACTIVITY_PID=$!

status=0
wait "$CAPTURE_PID" || status=$?
wait "$ACTIVITY_PID" || true
END_UTC=$(date --utc +%Y-%m-%dT%H:%M:%SZ)
END_EPOCH=$(date +%s)
THROTTLED_AFTER=$(vcgencmd get_throttled 2>/dev/null || true)
TEMP_AFTER=$(vcgencmd measure_temp 2>/dev/null || true)
LOAD_AFTER=$(cat /proc/loadavg)
PCAP_SHA256=$(sha256sum "$OUT/benign-pi5.pcap" | cut -d ' ' -f 1)
PCAP_BYTES=$(stat -c %s "$OUT/benign-pi5.pcap")
DEVICE_FRAMES_IPV4=$(sudo tcpdump -nr "$OUT/benign-pi5.pcap" 'ip' 2>/dev/null | wc -l)
DEVICE_FRAMES_IPV6=$(sudo tcpdump -nr "$OUT/benign-pi5.pcap" 'ip6' 2>/dev/null | wc -l)
DEVICE_FRAMES=$((DEVICE_FRAMES_IPV4 + DEVICE_FRAMES_IPV6))

export MODEL BOOT_ID KERNEL IFACE ADDRESS DEVICE_IPV4 CAPTURE_FILTER
export START_UTC END_UTC PCAP_SHA256 THROTTLED_BEFORE THROTTLED_AFTER
export TEMP_BEFORE TEMP_AFTER LOAD_BEFORE LOAD_AFTER
python3 - "$OUT/manifest.json" <<PY
import json, os, pathlib, sys
document = {
    "schema": "omniguard.benign-pi-capture/1",
    "card": "KAN-66",
    "declared_label": "benign",
    "label_basis": "owner-controlled Raspberry Pi; scripted normal activity only",
    "device": os.environ["MODEL"],
    "boot_id": os.environ["BOOT_ID"],
    "kernel": os.environ["KERNEL"],
    "interface": os.environ["IFACE"],
    "interface_address": os.environ["ADDRESS"],
    "device_ip": os.environ["DEVICE_IPV4"],
    "capture_filter": os.environ["CAPTURE_FILTER"],
    "start_utc": os.environ["START_UTC"],
    "end_utc": os.environ["END_UTC"],
    "duration_seconds": $((END_EPOCH - START_EPOCH)),
    "tcpdump_exit": ${status},
    "pcap": "benign-pi5.pcap",
    "pcap_bytes": ${PCAP_BYTES},
    "pcap_sha256": os.environ["PCAP_SHA256"],
    "device_frames": ${DEVICE_FRAMES},
    "device_frames_ipv4": ${DEVICE_FRAMES_IPV4},
    "device_frames_ipv6": ${DEVICE_FRAMES_IPV6},
    "scenarios": "scenarios.tsv",
    "capture_point": "device wlan0; not gateway transit",
    "throttled_before": os.environ["THROTTLED_BEFORE"],
    "throttled_after": os.environ["THROTTLED_AFTER"],
    "temperature_before": os.environ["TEMP_BEFORE"],
    "temperature_after": os.environ["TEMP_AFTER"],
    "load_before": os.environ["LOAD_BEFORE"],
    "load_after": os.environ["LOAD_AFTER"],
}
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
sha256sum "$OUT/manifest.json" "$OUT/scenarios.tsv" >"$OUT/SHA256SUMS"
exit "$status"
