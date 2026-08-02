"""argus-report-materialize skill entrypoint."""
from __future__ import annotations

from core.report import render_report, write_report


def invoke(output_dir, run_id, snapshot, agent_results, meta_decisions, policy,
           coverage=None) -> dict:
    data = render_report(run_id, snapshot, tuple(agent_results),
                         tuple(meta_decisions), policy, coverage=coverage)
    json_path, md_path = write_report(output_dir, data)
    return {"status": "succeeded", "report_json": str(json_path),
            "report_md": str(md_path)}
