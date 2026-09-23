"""Сводка всей выгрузки, независимо от выбранного на схеме окружения."""
from __future__ import annotations

from typing import Any

from pipeline.analysis import Analysis
from pipeline.roles import ROLES


def build_summary(analysis: Analysis) -> dict[str, Any]:
    nodes, edges = analysis.nodes, analysis.edges
    membership = nodes.set_index("gid").role
    enriched = edges.assign(
        sender_role=edges.src.map(membership), receiver_role=edges.dst.map(membership)
    )
    ranked_edges = enriched.sort_values(
        ["sum_kzt", "src", "dst"], ascending=[False, True, True]
    )
    edge_columns = ["src", "dst", "sender_role", "receiver_role", "sum_kzt", "n_tx"]
    role_rows, examples = [], []
    for role in ROLES:
        group = nodes[nodes.role.eq(role)]
        role_rows.append({
            "role": role, "count": len(group),
            "sum_in": float(group.sum_in.sum()), "sum_out": float(group.sum_out.sum()),
            "n_tx_in": int(group.n_tx_in.sum()), "n_tx_out": int(group.n_tx_out.sum()),
        })
        if group.empty:
            continue
        representative = group.sort_values(
            ["priority_score", "gid"], ascending=[False, True]
        ).iloc[0]
        gid = int(representative.gid)
        examples.append({
            "gid": gid, "role": role, "evidence": representative.evidence,
            "sum_in": float(representative.sum_in), "sum_out": float(representative.sum_out),
            "n_payers": int(representative.n_payers),
            "n_receivers": int(representative.n_receivers),
            "incoming": ranked_edges[ranked_edges.dst.eq(gid)].head(3)[edge_columns].to_dict("records"),
            "outgoing": ranked_edges[ranked_edges.src.eq(gid)].head(3)[edge_columns].to_dict("records"),
        })
    flows = (enriched.groupby(["sender_role", "receiver_role"], as_index=False)
             .agg(sum_kzt=("sum_kzt", "sum"), n_tx=("n_tx", "sum"))
             .sort_values(["sum_kzt", "sender_role", "receiver_role"], ascending=[False, True, True]))
    return {
        "overview": analysis.overview(), "roles": role_rows,
        "largest_transfers": ranked_edges.head(10)[edge_columns].to_dict("records"),
        "role_flows": flows.to_dict("records"), "examples": examples,
    }
