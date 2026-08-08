"""Generate report.html from the numbers already aggregated in aggregate.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from veredito.aggregate import ContractSummary


def render_report_html(
    summaries: Dict[str, ContractSummary],
    latency: Dict[str, Any],
    baseline_diff: Dict[str, Any],
    worst_examples: Dict[str, List[Dict[str, Any]]],
) -> str:
    rows = []
    for cid, s in sorted(summaries.items()):
        diff = baseline_diff.get(cid, {})
        regression_flag = "⚠️ regression" if diff.get("regression") else ""
        delta_txt = f"{diff['delta']:+.1%}" if diff.get("delta") is not None else "—"
        status_class = "ok" if s.pass_rate == 1.0 else ("warn" if s.pass_rate >= 0.8 else "fail")
        rows.append(
            f"<tr class='{status_class}'>"
            f"<td>{cid}</td><td>{s.type}</td>"
            f"<td>{s.passes}/{s.n}</td>"
            f"<td>{s.pass_rate:.1%}</td>"
            f"<td>[{s.ci[0]:.1%}, {s.ci[1]:.1%}]</td>"
            f"<td>{delta_txt} {regression_flag}</td>"
            "</tr>"
        )

    lat_rows = []
    for cid, l in sorted(latency.items()):
        violated = "⚠️ p95 violated" if l["p95_violated"] else ""
        lat_rows.append(
            f"<tr><td>{cid}</td><td>{l['min_s']}</td><td>{l['p50_s']}</td>"
            f"<td>{l['p95_s']}</td><td>{l['max_s']}</td>"
            f"<td>{l['p95_max_s'] if l['p95_max_s'] is not None else '—'}</td>"
            f"<td>{violated}</td></tr>"
        )

    worst_blocks = []
    for cid, examples in sorted(worst_examples.items()):
        items = "".join(
            f"<li>run {e['run']}: <code>{json.dumps(e.get('evidence'), ensure_ascii=False)}</code>"
            + (f" — error: {e['error']}" if e.get("error") else "")
            + "</li>"
            for e in examples
        )
        worst_blocks.append(f"<h4>{cid}</h4><ul>{items}</ul>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>UserZero — Verdict</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ margin-bottom: 0.2rem; }}
.subtitle {{ color: #666; margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }}
th {{ background: #f4f4f4; }}
tr.ok {{ background: #f0fff4; }}
tr.warn {{ background: #fffaf0; }}
tr.fail {{ background: #fff5f5; }}
code {{ font-size: 0.8rem; background: #f4f4f4; padding: 0.1rem 0.3rem; }}
</style>
</head>
<body>
<h1>UserZero — Verdict</h1>
<p class="subtitle">Generated on {datetime.now(timezone.utc).isoformat()}</p>

<h2>Pass rate by contract</h2>
<table>
<tr><th>Contract</th><th>Type</th><th>Passes</th><th>Pass rate</th><th>95% CI (Wilson)</th><th>Δ vs. baseline</th></tr>
{''.join(rows)}
</table>

<h2>Latency by declared phase</h2>
<table>
<tr><th>Contract</th><th>min (s)</th><th>p50 (s)</th><th>p95 (s)</th><th>max (s)</th><th>p95 limit (s)</th><th></th></tr>
{''.join(lat_rows)}
</table>

<h2>Worst examples for failed contracts</h2>
{''.join(worst_blocks) if worst_blocks else '<p>No failures — all contracts passed in 100% of runs.</p>'}

</body>
</html>"""
