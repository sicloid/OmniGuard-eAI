"""ADR-0004 decision 7b: download, audit, pack and score the untouched holdout once.

`score_spec.json` is committed before any holdout byte is downloaded and fixes the
frozen policy, the capture topology, the audit gate, what is reported and the one-shot
rule. The steps run in order, and each refuses to run if the one before it did not:

    python -m data.holdout.pipeline download --root ~/omniguard-data/holdout
    python -m data.holdout.pipeline audit    --root ~/omniguard-data/holdout
    python -m data.holdout.pipeline pack     --root ~/omniguard-data/holdout \\
        --out ~/omniguard-data/holdout-pack
    python -m data.holdout.pipeline score    --pack ~/omniguard-data/holdout-pack/windows.jsonl \\
        --artifact ~/omniguard-data/runs/kan19/operating --out ~/omniguard-data/runs/holdout

1. **download** fetches the files the selection manifest names, checks each size against
   the manifest and writes its SHA-256 into the manifest immediately.
2. **audit** recomputes every hash and counts EGRESS packets from each declared device;
   a capture whose device never sends outward cannot be scored.
3. **pack** builds windows with the frozen builder and label rule `window-label-1`.
4. **score** loads the frozen artifact with its pins, scores every window once at the
   frozen threshold, replays the frozen N = 2 / 300 s policy, and writes a record.
   It refuses to run if that record already exists.

These captures are malware captures, so the result is recall and containment on unseen
and seen families. Untouched benign FPR is not measured here (decision 7c), and benign
windows inside an infected capture are reported apart, never as a benign-device FPR.
"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SPEC = HERE / "score_spec.json"
SELECTION = HERE / "selection.json"
RECORD = HERE / "score_record.json"
REPORT_FILENAME = "holdout_report.json"
CHUNK = 1 << 20
WINDOW_SECONDS = 5


class HoldoutError(RuntimeError):
    """A step would score, or prepare to score, something it cannot vouch for."""


def load_spec(path: Path = SPEC) -> dict:
    from ipaddress import ip_address, ip_network

    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = spec.get("frozen", {})
    for name in ("model_sha256", "metadata_sha256", "threshold_policy_sha256"):
        value = str(frozen.get(name, ""))
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise HoldoutError(f"frozen.{name} must be a SHA-256 hex digest")
    if type(frozen.get("n")) is not int or frozen["n"] < 1:
        raise HoldoutError("frozen.n must be a positive integer")
    for name in ("threshold", "lease_seconds", "decision_delay_seconds", "max_result_age"):
        value = frozen.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise HoldoutError(f"frozen.{name} must be a non-negative number")
    for scenario, entry in spec.get("capture_topology", {}).items():
        if scenario == "rule":
            continue
        if ip_address(entry["device_ip"]) not in ip_network(entry["lan_cidr"]):
            raise HoldoutError(f"{scenario}: declared device is outside its declared LAN")
    return spec


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _picks(selection: dict) -> list[dict]:
    return list(selection["selection"])


def _files(pick: dict, root: Path) -> list[tuple[str, Path, int, str]]:
    """(manifest field, local path, expected bytes, remote relative path) per file."""
    folder = Path(root) / pick["scenario"]
    return [
        ("pcap_sha256", folder / pick["pcap"], pick["pcap_bytes"], pick["pcap"]),
        ("label_sha256", folder / "conn.log.labeled", pick["label_bytes"], pick["label_path"]),
    ]


def download(root: Path, selection_path: Path = SELECTION, *, opener=None, log=print) -> dict:
    """Fetch every selected file, check its size, and record its SHA-256 at once."""
    opener = opener or urllib.request.urlopen
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    base = selection["source"]["base_url"].rstrip("/")
    for pick in _picks(selection):
        for field, path, expected, remote in _files(pick, root):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size == expected:
                log(f"present  {path.name} ({expected} bytes)")
            else:
                url = f"{base}/{pick['scenario']}/{remote}"
                log(f"download {url}")
                partial = path.with_suffix(path.suffix + ".part")
                with opener(url) as response, open(partial, "wb") as handle:
                    for block in iter(lambda: response.read(CHUNK), b""):
                        handle.write(block)
                if partial.stat().st_size != expected:
                    size = partial.stat().st_size
                    partial.unlink()
                    raise HoldoutError(f"{url}: got {size} bytes, manifest says {expected}")
                partial.replace(path)
            digest = _sha256(path)
            recorded = pick.get(field)
            if recorded is not None and recorded != digest:
                raise HoldoutError(f"{path.name}: SHA-256 differs from the recorded {recorded}")
            pick[field] = digest
            log(f"sha256   {path.name} {digest}")
    selection["status"] = "downloaded; SHA-256 recorded; not audited; never scored"
    Path(selection_path).write_text(
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return selection


def verify_hashes(root: Path, selection_path: Path = SELECTION) -> None:
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    for pick in _picks(selection):
        for field, path, _, _ in _files(pick, root):
            recorded = pick.get(field)
            if recorded is None:
                raise HoldoutError(f"{pick['scenario']}: {field} was never recorded")
            if not path.is_file() or _sha256(path) != recorded:
                raise HoldoutError(f"{path}: missing or not the file whose hash was recorded")


def audit(root: Path, spec: dict, selection_path: Path = SELECTION, *, log=print) -> dict:
    """Hashes first, then direction: each declared device must send outward."""
    from core.schema import Direction
    from data.audit import pcap_record_count, summarize_pcap
    from data.samplepack.build import SHORT_LINK_HEADERS
    from sources.from_pcap import read_pcap
    from sources.packets import PacketError, PacketNormalizer

    verify_hashes(root, selection_path)
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    minimum = spec["audit_gate"]["min_device_egress_packets"]
    results = {}
    for pick in _picks(selection):
        scenario = pick["scenario"]
        topology = spec["capture_topology"][scenario]
        pcap = Path(root) / scenario / pick["pcap"]
        summary = summarize_pcap(pcap, [topology["lan_cidr"]])
        normalizer = PacketNormalizer([topology["lan_cidr"]], {topology["device_ip"]: scenario})
        egress = 0
        try:
            for packet in read_pcap(pcap, normalizer):
                egress += packet.direction is Direction.EGRESS
        except PacketError as exc:
            # Same rule as the builder: only a final record too short for its link
            # header ends the capture; anything else is corruption.
            if str(exc) not in SHORT_LINK_HEADERS or normalizer.stats.records != pcap_record_count(
                pcap
            ):
                raise
        except ValueError as exc:
            # A capture cut mid-record is used up to that point, as the builder does.
            if "truncated" not in str(exc):
                raise
        results[scenario] = {
            "direction_counts": summary.direction_counts,
            "device_egress_packets": egress,
            "ip_packets": summary.ip_packets,
        }
        log(f"{scenario}: device egress {egress}, directions {summary.direction_counts}")
        if egress < minimum:
            raise HoldoutError(f"{scenario}: declared device sent {egress} EGRESS packets")
    return results


def build_pack(root: Path, out_dir: Path, spec: dict, selection_path: Path = SELECTION) -> dict:
    from data.samplepack.build import CaptureSpec, build_sample_pack

    verify_hashes(root, selection_path)
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    base = selection["source"]["base_url"].rstrip("/")
    specs = []
    for pick in _picks(selection):
        scenario = pick["scenario"]
        topology = spec["capture_topology"][scenario]
        specs.append(
            CaptureSpec(
                group_id=scenario,
                pcap=Path(root) / scenario / pick["pcap"],
                lan_cidrs=(topology["lan_cidr"],),
                devices={topology["device_ip"]: f"holdout-{scenario}"},
                source_url=f"{base}/{scenario}/",
                license="IoT-23, Stratosphere Laboratory (CTU), CC BY 4.0 (Zenodo 4743746)",
                conn_log=Path(root) / scenario / "conn.log.labeled",
            )
        )
    return build_sample_pack(specs, Path(out_dir))


def capture_metrics(rows, frozen: dict) -> dict:
    """What the frozen policy did on one capture. `rows` are (start, result, malicious)."""
    from core.schema import Classification
    from model.nlease_run import malicious_overlap_seconds, replay_device

    malicious = [(s, r) for s, r, m in rows if m]
    benign = [(s, r) for s, r, m in rows if not m]
    flagged = sum(1 for _, r in malicious if r.classification == Classification.ANOMALOUS)
    outcome = replay_device(
        [(s, r) for s, r, _ in rows],
        n=frozen["n"],
        lease_seconds=frozen["lease_seconds"],
        spec={
            "replay": {
                "decision_delay_seconds": frozen["decision_delay_seconds"],
                "max_result_age": frozen["max_result_age"],
                "max_lease_seconds": frozen["max_lease_seconds"],
            }
        },
    )
    first_malicious = malicious[0][0] if malicious else None
    first_quarantine = outcome["episodes"][0]["start"] if outcome["episodes"] else None
    overlap = malicious_overlap_seconds(outcome["episodes"], [s for s, _ in malicious])
    malicious_seconds = len(malicious) * WINDOW_SECONDS
    return {
        "windows": len(rows),
        "malicious_windows": len(malicious),
        "anomalous_malicious_windows": flagged,
        "window_recall": round(flagged / len(malicious), 4) if malicious else None,
        "quarantined": first_quarantine is not None,
        "quarantines": outcome["quarantines"],
        "detection_delay_seconds": round(first_quarantine - first_malicious, 3)
        if first_quarantine is not None and first_malicious is not None
        else None,
        "malicious_time_blocked_fraction": round(overlap / malicious_seconds, 4)
        if malicious_seconds
        else None,
        "benign_windows_inside_infected_capture": len(benign),
        "benign_windows_inside_infected_capture_flagged": sum(
            1 for _, r in benign if r.classification == Classification.ANOMALOUS
        ),
    }


def score(pack: Path, artifact_dir: Path, out_dir: Path, spec: dict, *, record: Path = RECORD):
    """The only scoring of this holdout. Refuses if a record already exists."""
    from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
    from core.schema import Classification, DetectionResult
    from data.samplepack.build import read_windows
    from model.artifact import load_model
    from model.baseline_run import verify_pack
    from model.train import rf_scores

    if Path(record).exists():
        raise HoldoutError(f"{record} exists: this holdout has been scored and is consumed")
    frozen = spec["frozen"]
    provenance = verify_pack(Path(pack))
    artifact = load_model(
        Path(artifact_dir),
        expected_model_sha256=frozen["model_sha256"],
        expected_metadata_sha256=frozen["metadata_sha256"],
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
    )
    meta = artifact.metadata
    if _sha256(Path(artifact_dir) / "threshold.policy.json") != frozen["threshold_policy_sha256"]:
        raise HoldoutError("threshold.policy.json is not the frozen policy")
    if meta.threshold != frozen["threshold"]:
        raise HoldoutError(f"artifact threshold {meta.threshold} is not {frozen['threshold']}")

    windows = read_windows(Path(pack))
    scores = rf_scores(artifact.model, windows)
    by_capture: dict[str, list] = {}
    for window, value in zip(windows, scores, strict=True):
        result = DetectionResult(
            window.vector.device_id,
            window.vector.window_start,
            meta.model_id,
            meta.model_version,
            float(value),
            Classification.ANOMALOUS if value >= meta.threshold else Classification.NORMAL,
            meta.threshold,
        )
        by_capture.setdefault(window.group_id, []).append(
            (window.vector.window_start, result, window.malicious)
        )
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    roles = {pick["scenario"]: (pick["role"], pick["family"]) for pick in _picks(selection)}
    captures = {}
    for group, rows in sorted(by_capture.items()):
        rows.sort(key=lambda row: row[0])
        role, family = roles[group]
        captures[group] = {"role": role, "family": family, **capture_metrics(rows, frozen)}

    report = {
        "schema": spec["schema"],
        "decision": spec["decision"],
        "frozen": frozen,
        "pack": {
            "windows_sha256": provenance.windows_sha256,
            "manifest_sha256": provenance.manifest_sha256,
        },
        "selection_sha256": _sha256(SELECTION),
        "spec_sha256": _sha256(SPEC),
        "captures": captures,
        "untouched_benign_fpr": "not measured (ADR-0004 decision 7c)",
        "note": "Benign windows inside infected captures belong to the infected device and "
        "are not a benign-device FPR.",
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    (out_dir / REPORT_FILENAME).write_text(text, encoding="utf-8")
    Path(record).write_text(text, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="step", required=True)
    for name in ("download", "audit", "pack"):
        step = sub.add_parser(name)
        step.add_argument("--root", type=Path, required=True)
        if name == "pack":
            step.add_argument("--out", type=Path, required=True)
    step = sub.add_parser("score")
    step.add_argument("--pack", type=Path, required=True)
    step.add_argument("--artifact", type=Path, required=True)
    step.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = load_spec()
    if args.step == "download":
        download(args.root)
    elif args.step == "audit":
        print(json.dumps(audit(args.root, spec), indent=2, sort_keys=True))
    elif args.step == "pack":
        manifest = build_pack(args.root, args.out, spec)
        print(json.dumps(manifest["totals"], sort_keys=True))
    else:
        report = score(args.pack, args.artifact, args.out, spec)
        print(json.dumps(report["captures"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
