"""The KAN-52 headline figure, written from the report of the run that measured it.

The figure is plain SVG built here rather than by a plotting library: the project pins
its dependencies by hash, a figure is the one artefact a reader will quote, and text
output stays diffable and reproducible. Every coordinate comes from the report passed
in, so the figure cannot show a cell that was not measured.

Reading it: each point is one (N, lease) cell. Right means a benign device is
quarantined more often for nothing. Up means more of the attack's observed time went
unblocked. The bars are the block bootstrap interval from the same run: temporal
variability inside one capture, not the spread across devices. A dotted bar is a cell
whose resamples did not straddle the measurement, which means the blocks could not
reproduce it and the width is not an uncertainty anybody should quote.
"""

from pathlib import Path

WIDTH, HEIGHT = 920, 630
LEFT, RIGHT, TOP, BOTTOM = 96, 300, 64, 110
COLOURS = {1: "#c2410c", 2: "#1d4ed8", 3: "#047857", 5: "#6d28d9"}
FALLBACK = "#475569"
RADII = {30: 4.0, 60: 5.5, 120: 7.0, 300: 9.0}


class PlotError(ValueError):
    """The report does not hold what the headline figure claims to show."""


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _nice_ceiling(value: float) -> float:
    """A round upper bound, so the axis does not end on a measured number."""
    if value <= 0:
        return 1.0
    step = 0.1
    while step * 10 < value:
        step *= 10
    return step * (int(value / step) + 1)


def points(report: dict) -> list[dict]:
    """One plottable point per grid cell: benign cost against containment leakage."""
    benign = report["benign_captures"]
    infected = report["infected_captures"]
    if not benign or not infected:
        raise PlotError("the headline figure needs one benign and one infected capture")
    drawn = []
    for cell in report["cells"]:
        clean = cell["captures"][benign[0]]
        attacked = cell["captures"][infected[0]]
        if attacked["containment_leakage"] is None:
            raise PlotError(f"{infected[0]} has no malicious window time to leak")
        drawn.append(
            {
                "n": cell["n"],
                "lease_seconds": cell["lease_seconds"],
                "x": clean["quarantines_per_observed_hour"],
                "y": attacked["containment_leakage"],
                "x_interval": clean["bootstrap"]["quarantines_per_observed_hour"]["interval"],
                "y_interval": (attacked["bootstrap"].get("containment_leakage") or {}).get(
                    "interval"
                ),
                "reproduced": bool(
                    clean["bootstrap"]["quarantines_per_observed_hour"].get("reproduced", True)
                )
                and bool(
                    (attacked["bootstrap"].get("containment_leakage") or {}).get("reproduced", True)
                ),
            }
        )
    return drawn


def render(report: dict) -> str:
    drawn = points(report)
    operating = report["operating_point"]
    x_max = _nice_ceiling(max(max(p["x"], p["x_interval"][1]) for p in drawn))
    plot_width = WIDTH - LEFT - RIGHT
    plot_height = HEIGHT - TOP - BOTTOM

    def sx(value: float) -> float:
        return round(LEFT + plot_width * min(value, x_max) / x_max, 2)

    def sy(value: float) -> float:
        return round(TOP + plot_height * (1 - min(max(value, 0.0), 1.0)), 2)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="{LEFT}" y="30" font-size="17" font-weight="600" fill="#0f172a">'
        "KAN-52 &#8212; what containment costs a benign device, and what still gets out</text>",
        f'<text x="{LEFT}" y="50" font-size="12" fill="#475569">'
        f"Frozen KAN-19 model and threshold, replayed through DevicePolicy on the "
        f"{_escape(report['evaluated_split'])} split. One point per (N, lease) cell."
        + (" One-shot test confirmation." if report["evaluated_split"] == "test" else "")
        + "</text>",
    ]

    for tick in range(0, 11, 2):
        value = tick / 10
        y = sy(value)
        out.append(
            f'<line x1="{LEFT}" y1="{y}" x2="{LEFT + plot_width}" y2="{y}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{LEFT - 10}" y="{y + 4}" font-size="11" fill="#475569" '
            f'text-anchor="end">{value:.0%}</text>'
        )
    for step in range(6):
        value = x_max * step / 5
        x = sx(value)
        out.append(
            f'<line x1="{x}" y1="{TOP}" x2="{x}" y2="{TOP + plot_height}" '
            f'stroke="#f1f5f9" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x}" y="{TOP + plot_height + 20}" font-size="11" fill="#475569" '
            f'text-anchor="middle">{value:g}</text>'
        )
    out.append(
        f'<line x1="{LEFT}" y1="{TOP + plot_height}" x2="{LEFT + plot_width}" '
        f'y2="{TOP + plot_height}" stroke="#94a3b8" stroke-width="1.5"/>'
    )
    out.append(
        f'<line x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{TOP + plot_height}" '
        f'stroke="#94a3b8" stroke-width="1.5"/>'
    )
    out.append(
        f'<text x="{LEFT + plot_width / 2}" y="{TOP + plot_height + 42}" font-size="12.5" '
        f'fill="#0f172a" text-anchor="middle">false quarantines per observed benign '
        f"device-hour &#8594;</text>"
    )
    out.append(
        f'<text x="26" y="{TOP + plot_height / 2}" font-size="12.5" fill="#0f172a" '
        f'text-anchor="middle" transform="rotate(-90 26 {TOP + plot_height / 2})">'
        "containment leakage (malicious time not blocked) &#8594;</text>"
    )

    for point in drawn:
        colour = COLOURS.get(point["n"], FALLBACK)
        radius = RADII.get(point["lease_seconds"], 5.0)
        x, y = sx(point["x"]), sy(point["y"])
        low, high = sx(point["x_interval"][0]), sx(point["x_interval"][1])
        # A cell the resampling could not reproduce gets a dotted bar: the number is
        # still the measurement, but the width around it should not be quoted.
        dash = "" if point["reproduced"] else ' stroke-dasharray="2 2"'
        out.append(
            f'<line x1="{low}" y1="{y}" x2="{high}" y2="{y}" stroke="{colour}" '
            f'stroke-width="1" opacity="0.45"{dash}/>'
        )
        if point["y_interval"]:
            out.append(
                f'<line x1="{x}" y1="{sy(point["y_interval"][0])}" x2="{x}" '
                f'y2="{sy(point["y_interval"][1])}" stroke="{colour}" stroke-width="1" '
                f'opacity="0.45"{dash}/>'
            )
        if point["n"] == operating["n"] and point["lease_seconds"] == operating["lease_seconds"]:
            out.append(
                f'<circle cx="{x}" cy="{y}" r="{radius + 6}" fill="none" stroke="{colour}" '
                f'stroke-width="1.5" stroke-dasharray="3 2"/>'
            )
            out.append(
                f'<text x="{x + radius + 12}" y="{y + 4}" font-size="11.5" font-weight="600" '
                f'fill="{colour}">frozen: N={operating["n"]}, '
                f"{operating['lease_seconds']:g} s</text>"
            )
        out.append(
            f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{colour}" fill-opacity="0.85" '
            f'stroke="#ffffff" stroke-width="1"/>'
        )

    legend_x = LEFT + plot_width + 34
    out.append(
        f'<text x="{legend_x}" y="{TOP + 4}" font-size="12" font-weight="600" fill="#0f172a">'
        "N (consecutive anomalies)</text>"
    )
    for index, n in enumerate(sorted(COLOURS)):
        y = TOP + 26 + index * 20
        out.append(
            f'<circle cx="{legend_x + 7}" cy="{y - 4}" r="6" fill="{COLOURS[n]}" '
            f'fill-opacity="0.85"/>'
        )
        out.append(
            f'<text x="{legend_x + 22}" y="{y}" font-size="11.5" fill="#334155">N = {n}</text>'
        )
    out.append(
        f'<text x="{legend_x}" y="{TOP + 128}" font-size="12" font-weight="600" fill="#0f172a">'
        "lease (marker size)</text>"
    )
    for index, lease in enumerate(sorted(RADII)):
        y = TOP + 152 + index * 22
        out.append(
            f'<circle cx="{legend_x + 7}" cy="{y - 4}" r="{RADII[lease]}" fill="{FALLBACK}" '
            f'fill-opacity="0.7"/>'
        )
        out.append(
            f'<text x="{legend_x + 22}" y="{y}" font-size="11.5" fill="#334155">{lease} s</text>'
        )
    out.append(
        f'<text x="{legend_x}" y="{TOP + 262}" font-size="11" fill="#475569">'
        "bars: 95% basic block</text>"
    )
    out.append(
        f'<text x="{legend_x}" y="{TOP + 278}" font-size="11" fill="#475569">'
        "bootstrap, one capture</text>"
    )

    benign, infected = report["benign_captures"][0], report["infected_captures"][0]
    unreproduced = sum(1 for point in drawn if not point["reproduced"])
    footnotes = [
        f"Benign: {benign}, {report['observed'][benign]['observed_hours']:g} observed "
        f"device-hours. Infected: {infected}, "
        f"{report['observed'][infected]['observed_hours']:g} observed device-hours. "
        "The two are never pooled.",
        "Zero observed false quarantines is not zero risk: one device over a few hours "
        "cannot show a rate this data has no power to measure.",
        "Leakage here is policy intent. Bytes delivered before the kernel ACK are KAN-33 "
        "and the G8 run, reported separately.",
        f"Dotted bars ({unreproduced} of {len(drawn)} cells): the resampled blocks did not "
        "straddle the measurement, so that width is not an uncertainty to quote."
        if unreproduced
        else "Every cell's resamples straddle its measurement.",
    ]
    for index, line in enumerate(footnotes):
        out.append(
            f'<text x="{LEFT}" y="{HEIGHT - 56 + index * 14}" font-size="10.5" fill="#64748b">'
            f"{_escape(line)}</text>"
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_plot(report: dict, path: Path) -> Path:
    path = Path(path)
    path.write_text(render(report), encoding="utf-8")
    return path
