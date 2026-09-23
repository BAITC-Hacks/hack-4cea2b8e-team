"""Единая точка запуска пайплайна.

Must-have №1: один запуск от сырых .parquet до трёх выгрузок, без ручных шагов,
меньше 5 минут.

    python -m pipeline.run --data data/ --out out/

Создаёт:
    out/nodes_roles.csv   строка на каждый узел
    out/clusters.csv      строка на кластер
    out/top_nodes.csv     ранжированный топ (не менее 20 узлов)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from . import graph, roles


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="папка с edges/nodes/transactions.parquet")
    ap.add_argument("--out", default="out", help="куда положить выгрузки")
    ap.add_argument("--top", type=int, default=25, help="размер топ-листа (минимум 20)")
    args = ap.parse_args()

    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("1/5 загрузка данных")
    edges, nodes, tx = graph.load(args.data)
    print(f"      узлов {len(nodes)}, рёбер {len(edges)}, транзакций {len(tx)}")

    print("2/5 метрики узлов")
    g = graph.build_graph(edges)
    m = graph.node_metrics(edges, nodes)
    m = graph.add_components(m, g)

    print("3/5 кластеризация")
    m = graph.cluster(m, g)

    print("4/5 роли и приоритеты")
    m = roles.assign(m)
    m = roles.priority(m)

    print("5/5 выгрузки")
    m[["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]].to_csv(
        out / "nodes_roles.csv", index=False
    )

    cl = (
        m.groupby("cluster_id")
        .agg(
            n_nodes=("gid", "count"),
            n_seed=("is_seed", "sum"),
            sum_kzt_internal=("sum_out", "sum"),
        )
        .reset_index()
    )
    cl["top_gids"] = cl.cluster_id.map(
        lambda c: "|".join(
            m[m.cluster_id == c].nlargest(5, "priority_score").gid.astype(str)
        )
    )
    cl["hypothesis"] = cl.apply(
        lambda r: f"Кластер из {r.n_nodes} узлов, {int(r.n_seed)} из исходного списка. "
        f"Требует проверки как возможная группа.",
        axis=1,
    )
    cl.to_csv(out / "clusters.csv", index=False)

    top = m.nlargest(max(args.top, 20), "priority_score").reset_index(drop=True)
    top.insert(0, "rank", top.index + 1)
    top = top.rename(columns={"evidence": "why"})
    top[["rank", "gid", "role", "priority_score", "why"]].to_csv(
        out / "top_nodes.csv", index=False
    )

    print(f"\nГотово за {time.time() - t0:.1f} с. Файлы в {out}/")
    print(m.role.value_counts().to_string())


if __name__ == "__main__":
    main()
