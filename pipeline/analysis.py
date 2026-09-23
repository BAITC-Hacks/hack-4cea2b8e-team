"""Единый результат анализа для CLI, выгрузок и HTTP API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from . import graph, roles, typologies


LIMITATIONS = [
    "Выводы — гипотезы для проверки, а не утверждения о виновности.",
    "Видны только внутрибанковские переводы в пределах выборки; полный баланс неизвестен.",
    "Исходящие за четвёртым коленом и переводы ниже 5 000 ₸ не видны.",
    "У исходных клиентов входящие неполны; отношение потоков не используется для их роли.",
    "role_score — эвристическая оценка правила, а не вероятность виновности или калиброванная вероятность роли.",
    "Связи и совпадение дат не доказывают движение одних и тех же денег; время внутри дня неизвестно.",
]

NODE_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence", "typologies"]
TOP_COLUMNS = ["rank", "gid", "role", "priority_score", "why", "typologies"]


@dataclass
class Analysis:
    network: nx.DiGraph
    nodes: pd.DataFrame
    edges: pd.DataFrame
    transactions: pd.DataFrame
    clusters: pd.DataFrame

    def ranked(self) -> pd.DataFrame:
        return self.nodes.sort_values(["priority_score", "gid"], ascending=[False, True])

    def top(self, limit: int = 25) -> pd.DataFrame:
        top = self.ranked().head(limit).reset_index(drop=True).copy()
        top.insert(0, "rank", top.index + 1)
        top = top.rename(columns={"evidence": "why"})
        return top[TOP_COLUMNS]

    def tables(self, limit: int = 25) -> dict[str, pd.DataFrame]:
        return {
            "nodes_roles.csv": self.nodes[NODE_COLUMNS],
            "clusters.csv": self.clusters,
            "top_nodes.csv": self.top(max(20, limit)),
        }

    def overview(self) -> dict[str, Any]:
        tx = self.transactions
        return {
            "n_nodes": len(self.nodes), "n_edges": len(self.edges),
            "n_transactions": len(tx), "n_seed": int(self.nodes.is_seed.sum()),
            "sum_kzt": float(self.edges.sum_kzt.sum()),
            "n_clusters": len(self.clusters),
            "n_components": nx.number_weakly_connected_components(self.network),
            "n_isolates": nx.number_of_isolates(self.network),
            "n_truncated": int(self.nodes.truncated.sum()),
            "n_seed_without_outgoing": int((self.nodes.is_seed & self.nodes.n_receivers.eq(0)).sum()),
            "period": {"from": tx.date.min().date().isoformat() if len(tx) else None,
                       "to": tx.date.max().date().isoformat() if len(tx) else None},
            "roles": {role: int(self.nodes.role.eq(role).sum()) for role in roles.ROLES},
            "limitations": LIMITATIONS,
            "thresholds": roles.THRESHOLDS,
            "priority_formula": "0.5 × вес роли + 0.3 × нормированный оборот + 0.2 × нормированное число связей",
        }


def cluster_summary(m: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    membership = m.set_index("gid").cluster_id
    e = edges.assign(source_cluster=edges.src.map(membership), target_cluster=edges.dst.map(membership))
    internal = e[e.source_cluster.eq(e.target_cluster)].groupby("source_cluster").sum_kzt.sum()
    rows = []
    for cid, group in m.groupby("cluster_id", sort=True):
        ranked = group.sort_values(["priority_score", "gid"], ascending=[False, True])
        signals = group[group.role.ne("peripheral")].role.value_counts()
        if len(group) == 1 and group.n_payers.sum() + group.n_receivers.sum() == 0:
            hypothesis = "Изолированный клиент: в выборке нет переводов; для гипотезы о связях нужны дополнительные данные."
        elif signals.empty:
            hypothesis = "Сообщество по структуре переводов; выраженных ролевых признаков не выявлено."
        else:
            labels = {"coordinator": "связывающих узлов", "consolidator": "точек консолидации",
                      "distributor": "распределителей", "transit": "транзитных узлов", "terminal": "возможных конечных получателей"}
            main = signals.index[0]
            hypothesis = f"Сообщество с признаками {labels[main]} ({int(signals.iloc[0])}). Проверить потоки через приоритетные узлы."
        rows.append({"cluster_id": int(cid), "n_nodes": len(group),
                     "n_seed": int(group.is_seed.sum()),
                     "sum_kzt_internal": float(internal.get(cid, 0)),
                     "top_gids": "|".join(ranked.head(5).gid.astype(str)),
                     "hypothesis": hypothesis})
    return pd.DataFrame(rows)


def analyze(data_dir: str | Path) -> Analysis:
    edges, nodes, tx = graph.load(data_dir, reconcile=True)
    network = graph.build_graph(edges, nodes)
    metrics = graph.cluster(graph.add_components(graph.node_metrics(edges, nodes), network), network)
    metrics = typologies.attach(metrics, tx, network)
    metrics = roles.priority(roles.assign(metrics))
    # Краткое доказательство роли не обрезаем посередине; типологии храним отдельно.
    metrics["typology_evidence"] = metrics.apply(typologies.describe, axis=1)
    metrics = metrics.sort_values("gid").reset_index(drop=True)
    return Analysis(network, metrics, edges, tx, cluster_summary(metrics, edges))
