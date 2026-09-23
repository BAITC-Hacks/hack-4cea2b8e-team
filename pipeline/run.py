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
import json
import time
from pathlib import Path

from . import typologies
from .analysis import analyze


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="папка с edges/nodes/transactions.parquet")
    ap.add_argument("--out", default="out", help="куда положить выгрузки")
    ap.add_argument("--top", type=int, default=25, help="размер топ-листа (минимум 20)")
    ap.add_argument("--extended", action="store_true", help="добавить отдельные CSV с типологиями")
    args = ap.parse_args()

    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("Расчёт графа, ролей, кластеров и типологий")
    result = analyze(args.data)
    g, m = result.network, result.nodes
    print(f"Узлов {len(m)}, рёбер {len(result.edges)}, транзакций {len(result.transactions)}")
    for name, table in result.tables(args.top, extended=args.extended).items():
        table.to_csv(out / name, index=False)
    top = result.top(max(args.top, 20))

    # Устойчивость сети: что даст изъятие топ-N. Аргумент «начинать стоит с них».
    res = typologies.resilience(g, top.gid.tolist())
    (out / "resilience.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nГотово за {time.time() - t0:.1f} с. Файлы в {out}/")
    print(m.role.value_counts().to_string())
    print(
        f"\nИзъятие топ-{res['removed']}: компонент {res['components_before']} → "
        f"{res['components_after']}, крупнейшая {res['largest_before']} → "
        f"{res['largest_after']} (-{res['largest_drop_pct']}%)"
    )


if __name__ == "__main__":
    main()
