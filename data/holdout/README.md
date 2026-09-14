# Untouched IoT-23 malware holdout — selection

Owner: R1 (Onur). Decision: [ADR-0004](../../docs/adr/0004-dataset-source.md), decision 7b.
Manifest: [`selection.json`](selection.json). Check:
`python -m data.holdout.selection --check`.

**Status: selected, not downloaded, never scored.**

The six IoT-23 captures in the sample pack are development data. KAN-18 and KAN-21 used
all of them, so none of them can serve as an untouched test. This directory records which
unused IoT-23 malware captures become the untouched holdout. The choice was made **before
download**, from published metadata only.

## Approval

On 14 September 2026 Şükrü (Lead/R2) approved three things in team chat (see also KAN-13
comment 10476):

- a total download budget of **10,000,000,000 bytes**;
- equal sizes are broken by the **smaller numeric scenario id**;
- selection and exclusions are written into the manifest before any download.

The ADR as a whole stays PROPOSED. This approval does not cover UNSW-IoTraffic.

## Rule

1. **Candidates.** The 17 IoT-23 malware scenarios not used in development. Their
   families come from the Stratosphere scenario table.
2. **Primary capture only.** Each scenario has one full capture named
   `YYYY-MM-DD[-HH-MM-SS]-<device IP>.pcap`. Derived excerpts (`-only5000`,
   `.only15000000`, per-host or per-port cuts, `telnet.pcap`) are not candidates.
3. **Labels required.** A candidate needs a published `conn.log.labeled`.
   - Malware captures contain benign flows too, so a declared label is not acceptable here.
   - 43-1 keeps its labels under `labeled/` rather than `bro/`. That is recorded as a
     different path, not as an exclusion.
4. **Size.** Size is the HTTP `Content-Length` of the primary capture. The budget
   counts the capture plus its label file.
5. **Seen family.** Mirai. The smallest primary capture among Mirai scenarios other
   than 34-1 is chosen.
6. **Unseen families.** The first two families in this fixed order whose smallest
   primary capture fits the remaining budget: Torii, Okiru, Gagfyt, Kenjiro, IRCBot,
   Linux.Hajime, Hide and Seek, Trojan.
7. **Ties.** Equal sizes go to the smaller numeric scenario id, so 9-1 comes before
   17-1 and not the other way round.

**Excluded:** 7-1 (Linux.Mirai), because it cannot be separated from Mirai.

## Selection

| Role | Scenario | Family | Primary capture (bytes) | Label (bytes) | Download (bytes) |
|---|---|---|---|---|---|
| Seen family | CTU-IoT-Malware-Capture-48-1 | Mirai | 1,222,967,296 | 531,738,215 | 1,754,705,511 |
| Unseen family | CTU-IoT-Malware-Capture-20-1 | Torii | 4,057,401 | 419,604 | 4,477,005 |
| Unseen family | CTU-IoT-Malware-Capture-36-1 | Okiru | 1,039,545,119 | 1,787,852,355 | 2,827,397,474 |
| **Total** | | | | | **4,586,579,990** |

How each pick was reached:

- **Mirai:** 48-1 is the smallest; the next are 49-1 at 1,381,228,544 bytes and 44-1 at
  1,822,543,872 bytes.
- **Torii:** 20-1 at 4,057,401 bytes beats 21-1 at 4,063,997 bytes on size alone, so
  the tie-break was not needed.
- **Okiru:** 36-1 is the family's only scenario.
- **Families not reached:** Gagfyt (60-1, a 22 GB capture) and every family after it,
  because Torii and Okiru both fit the budget first.

Known limitation: 20-1's capture is only 4 MB and will give few windows. It is kept
anyway. The rule is fixed, and swapping it for a larger capture after seeing sizes would
be exactly the kind of choice this manifest exists to prevent.

## What may and may not happen next

- **Allowed:** download the three selected files; add each file's SHA-256 to
  `selection.json` immediately; run the `data/audit.py` direction and label audit; build
  a pack with the frozen builder.
- **Forbidden:** training, validation, or choosing thresholds, N, lease or features on
  these captures. No model score may be produced before these are recorded:
  `feature_schema_version`, `model_sha256`, the metadata hash, the threshold policy hash,
  N/lease, and the development pack's `windows_sha256`.
- The holdout is scored **once**. If anything is tuned afterwards, it counts as consumed.
