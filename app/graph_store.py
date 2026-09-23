"""Загрузка и запросы к графу денежных переводов."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from pipeline.analysis import Analysis, analyze


class GraphStore:
    """Граф и рассчитанные метрики, загруженные один раз при старте."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.nodes: dict[int, dict[str, Any]] = {}
        self.analysis: Analysis | None = None

    def load(self, data_dir: str | Path, out_dir: str | Path | None = None) -> None:
        del out_dir  # Оставлен в сигнатуре для единой точки загрузки приложения.
        result = analyze(data_dir)
        self.analysis = result
        self.graph = result.network
        self.nodes = {
            int(row.gid): self._record(row)
            for row in result.nodes.itertuples(index=False)
        }

    @staticmethod
    def _record(row: Any) -> dict[str, Any]:
        record = row._asdict()
        if pd.isna(record.get("passthrough")):
            record["passthrough"] = None
        for key in ("gid", "depth", "cluster_id", "n_payers", "n_receivers"):
            if key in record:
                record[key] = int(record[key])
        for key in ("is_seed", "truncated", "ratio_reliable"):
            if key in record:
                record[key] = bool(record[key])
        for key in ("role_score", "priority_score", "sum_in", "sum_out"):
            if key in record:
                record[key] = float(record[key])
        # Контракт web/graph.html; исходные имена сохраняются для CLI и API.
        record["in_degree"] = record["n_payers"]
        record["out_degree"] = record["n_receivers"]
        record["passthrough_ratio"] = record["passthrough"] if record["ratio_reliable"] else None
        return record

    def node(self, gid: int) -> dict[str, Any] | None:
        return self.nodes.get(gid)

    def subgraph_nodes(self, gid: int, hops: int, limit: int, direction: str = "both") -> tuple[list[dict[str, Any]], bool]:
        network = self.graph if direction == "out" else self.graph.reverse(copy=False) if direction == "in" else self.graph.to_undirected(as_view=True)
        reachable = nx.single_source_shortest_path_length(
            network, gid, cutoff=hops
        )
        ordered = sorted(
            reachable,
            key=lambda node: (reachable[node], -self.nodes[node]["priority_score"], node),
        )
        truncated = len(ordered) > limit
        selected = ordered[:limit]
        return [self.nodes[node] for node in selected], truncated

    def cluster_nodes(self, cluster_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
        ordered = sorted(
            (
                node
                for node, record in self.nodes.items()
                if record["cluster_id"] == cluster_id
            ),
            key=lambda node: (-self.nodes[node]["priority_score"], node),
        )
        truncated = len(ordered) > limit
        return [self.nodes[node] for node in ordered[:limit]], truncated

    def edges_between(self, node_ids: set[int]) -> list[dict[str, Any]]:
        edges = []
        for src, dst, data in self.graph.edges(data=True):
            if src in node_ids and dst in node_ids:
                edges.append(
                    {
                        "src": int(src),
                        "dst": int(dst),
                        "sum_kzt": float(data["sum_kzt"]),
                        "n_tx": int(data["n_tx"]),
                        "source": int(src),
                        "target": int(dst),
                        "amount": float(data["sum_kzt"]),
                        "tx_count": int(data["n_tx"]),
                    }
                )
        return sorted(edges, key=lambda edge: (edge["src"], edge["dst"]))

    def top(self, limit: int) -> list[dict[str, Any]]:
        ordered = sorted(
            self.nodes.values(),
            key=lambda record: (-record["priority_score"], record["gid"]),
        )[:limit]
        return [
            {
                "rank": rank,
                "gid": record["gid"],
                "role": record["role"],
                "priority_score": record["priority_score"],
                "why": record["evidence"],
            }
            for rank, record in enumerate(ordered, start=1)
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        return [
            {"gid": record["gid"], "role": record["role"]}
            for record in sorted(self.nodes.values(), key=lambda item: item["gid"])
            if str(record["gid"]).startswith(query)
        ][:20]

    def filtered(self, *, role: str | None = None, cluster_id: int | None = None,
                 is_seed: bool | None = None, truncated: bool | None = None,
                 min_priority: float = 0, q: str = "", typology: str | None = None) -> list[dict[str, Any]]:
        return sorted((r for r in self.nodes.values()
                       if (role is None or r["role"] == role)
                       and (cluster_id is None or r["cluster_id"] == cluster_id)
                       and (is_seed is None or r["is_seed"] == is_seed)
                       and (truncated is None or r["truncated"] == truncated)
                       and r["priority_score"] >= min_priority
                       and str(r["gid"]).startswith(q)
                       and (typology is None or typology in r["typologies"].split("|"))),
                      key=lambda r: (-r["priority_score"], r["gid"]))

    def card(self, gid: int) -> dict[str, Any] | None:
        record = self.node(gid)
        if record is None:
            return None
        warnings = ["Полный баланс неизвестен; суммы относятся только к наблюдаемой выборке."]
        next_steps = ["Проверить назначения и контекст переводов по банковским данным."]
        if record["truncated"]:
            warnings.append("Граница обхода: дальнейшие исходящие переводы не видны.")
            next_steps.append("Запросить исходящие переводы на следующее колено.")
        if record["is_seed"]:
            warnings.append("Входящие исходного клиента неполны; отношение потоков не определяет роль.")
            next_steps.append("Запросить полную входящую выписку исходного клиента.")
        if record["n_payers"] + record["n_receivers"] == 0:
            warnings.append("В этой выгрузке нет связей клиента; это не доказывает отсутствия активности.")
        return {**record, "warnings": warnings, "next_steps": next_steps,
                "score_kind": "rule_based_heuristic",
                "priority_breakdown": {"role": record["priority_role"],
                                       "turnover": record["priority_turnover"],
                                       "connections": record["priority_connections"]}}

    def path(self, source: int, target: int, max_hops: int) -> dict[str, Any]:
        # BFS с пределом глубины; не перечисляем экспоненциальное число маршрутов.
        paths = nx.single_source_shortest_path(self.graph, source, cutoff=max_hops)
        path = paths.get(target, [])
        return {"source": source, "target": target, "found": bool(path),
                "gids": path, "nodes": [self.nodes[n] for n in path],
                "edges": [{"src": a, "dst": b, **self.graph[a][b]} for a, b in zip(path, path[1:])],
                "max_hops": max_hops,
                "interpretation": "Кратчайший направленный маршрут по числу связей; движение одних и тех же денег не доказано."}

    def common_receivers(self, gids: list[int], limit: int) -> dict[str, Any]:
        shared = set.intersection(*(set(self.graph.successors(gid)) for gid in gids))
        rows = []
        for receiver in shared:
            edges = [{"src": source, "dst": receiver, **self.graph[source][receiver]} for source in gids]
            rows.append({"node": self.nodes[receiver], "sum_kzt": sum(e["sum_kzt"] for e in edges), "edges": edges})
        rows.sort(key=lambda r: (-r["sum_kzt"], r["node"]["gid"]))
        return {"gids": gids, "total": len(rows), "items": rows[:limit],
                "truncated": len(rows) > limit, "hops": 1}

    def transactions(self, gid: int, limit: int, offset: int, direction: str,
                     date_from: str | None = None, date_to: str | None = None,
                     counterparty: int | None = None) -> dict[str, Any]:
        assert self.analysis is not None
        tx = self.analysis.transactions
        mask = tx.src.eq(gid) if direction == "out" else tx.dst.eq(gid) if direction == "in" else tx.src.eq(gid) | tx.dst.eq(gid)
        if counterparty is not None:
            mask &= (tx.src.eq(gid) & tx.dst.eq(counterparty)) | (tx.dst.eq(gid) & tx.src.eq(counterparty))
        if date_from:
            mask &= tx.date.ge(pd.Timestamp(date_from))
        if date_to:
            mask &= tx.date.lt(pd.Timestamp(date_to) + pd.Timedelta(days=1))
        selected = tx[mask].sort_values(["date", "src", "dst", "sum_kzt"], ascending=[False, True, True, False])
        page = selected.iloc[offset:offset + limit].copy()
        page["date"] = page.date.dt.strftime("%Y-%m-%d")
        return {"total": len(selected), "sum_kzt": float(selected.sum_kzt.sum()),
                "items": page.to_dict("records"), "offset": offset, "limit": limit}

    def flows(self, gid: int, direction: str, limit: int, offset: int) -> dict[str, Any]:
        """Один шаг расследования: крупнейшие прямые связи, без рёбер между соседями."""
        assert self.analysis is not None
        tx = self.analysis.transactions
        outgoing = direction == "out"
        selected = tx[tx.src.eq(gid) if outgoing else tx.dst.eq(gid)]
        counterpart = "dst" if outgoing else "src"
        grouped = selected.groupby(counterpart).agg(
            sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"),
            first_date=("date", "min"), last_date=("date", "max"),
        ).reset_index().rename(columns={counterpart: "gid"})
        grouped = grouped.sort_values(["sum_kzt", "gid"], ascending=[False, True])
        total_amount = float(grouped.sum_kzt.sum())
        page = grouped.iloc[offset:offset + limit]
        items, edges = [], []
        for rank, row in enumerate(page.itertuples(index=False), start=offset + 1):
            neighbor = int(row.gid)
            source, target = (gid, neighbor) if outgoing else (neighbor, gid)
            first, last = row.first_date.date().isoformat(), row.last_date.date().isoformat()
            amount, count = float(row.sum_kzt), int(row.n_tx)
            share = amount / total_amount if total_amount else 0.0
            edge = {"src": source, "dst": target, "source": source, "target": target,
                    "sum_kzt": amount, "amount": amount, "n_tx": count, "tx_count": count,
                    "first_date": first, "last_date": last}
            edges.append(edge)
            items.append({"rank": rank, "node": self.nodes[neighbor], "edge": edge,
                          "share": share,
                          "explanation": f"{count} переводов на {amount:,.2f} ₸; "
                          f"{share:.1%} наблюдаемых {'исходящих' if outgoing else 'входящих'} "
                          f"выбранного клиента. Период: {first} — {last}."})
        ids = list(dict.fromkeys([gid] + [int(r.gid) for r in page.itertuples(index=False)]))
        shown = len(items)
        return {"center": gid, "direction": direction, "hops": 1,
                "card": self.card(gid), "items": items,
                "nodes": [self.nodes[n] for n in ids], "edges": edges,
                "total_counterparties": len(grouped), "shown_counterparties": shown,
                "hidden_counterparties": len(grouped) - shown,
                "total_amount": total_amount, "shown_amount": float(page.sum_kzt.sum()),
                "total_transactions": len(selected), "offset": offset, "limit": limit,
                "has_more": offset + shown < len(grouped),
                "next_offset": offset + shown if offset + shown < len(grouped) else None,
                "interpretation": "Прямые переводы в пределах выборки. При раскрытии следующей ветки происхождение тех же денег не доказано."}
