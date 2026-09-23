"""Первое, что запускаем, когда появились данные.

Показывает реальные распределения, по которым подбираются пороги в
pipeline/roles.py: THRESHOLDS должны опираться на данные, а не на догадки.

    python scripts/explore.py --data data/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import graph  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()

    edges, nodes, tx = graph.load(a.data)
    print("=== РАЗМЕРЫ ===")
    print(f"узлы {len(nodes)}, рёбра {len(edges)}, транзакции {len(tx)}")
    print("\nколонки:")
    for name, df in [("edges", edges), ("nodes", nodes), ("transactions", tx)]:
        print(f"  {name}: {list(df.columns)}")

    print("\n=== КОЛЕНА ===")
    print(nodes.depth.value_counts().sort_index().to_string())
    print("seed:", int(nodes.is_seed.sum()))

    g = graph.build_graph(edges)
    m = graph.node_metrics(edges, nodes)
    m = graph.add_components(m, g)

    print("\n=== ЛОВУШКА: ОБРЫВ НА ПОСЛЕДНЕМ КОЛЕНЕ ===")
    print("узлов с truncated=True:", int(m.truncated.sum()))
    print("(наивное правило out_degree==0 -> terminal дало бы столько ложных)")

    print("\n=== РАСПРЕДЕЛЕНИЯ ДЛЯ ПОДБОРА ПОРОГОВ ===")
    for col in ["n_payers", "n_receivers", "sum_in", "sum_out", "passthrough"]:
        q = m[col].describe(percentiles=[0.5, 0.9, 0.95, 0.99])
        print(f"\n{col}:")
        print(q.to_string())

    print("\n=== КАНДИДАТЫ В РОЛИ ===")
    print("плательщиков >= 8:", int((m.n_payers >= 8).sum()))
    print("получателей >= 20:", int((m.n_receivers >= 20).sum()))
    print("passthrough 0.8-1.2:", int(m.passthrough.between(0.8, 1.2).sum()))

    print("\n=== КОМПОНЕНТЫ ===")
    print(m.component.value_counts().head(5).to_string())


if __name__ == "__main__":
    main()
