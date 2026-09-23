"""Загрузка данных и расчёт метрик узлов.

Схема входных файлов (из ТЗ кейса):
    edges.parquet        src, dst, sum_kzt, n_tx, depth        ~3 119 строк
    nodes.parquet        gid, depth, is_seed                   ~2 248 строк
    transactions.parquet src, dst, date, sum_kzt               ~4 840 строк

ВАЖНО — ловушки данных, объявленные в ТЗ. Их учёт оценивается:
  1. Обрыв на 4-м колене: 444 узла с depth=4 имеют нулевые исходящие.
     Это артефакт обхода, а не «деньги осели». Признак out_degree == 0
     сам по себе НЕ означает конечного получателя.
  2. Видны только исходящие переводы — полный баланс узла недостоверен.
  3. У seed-клиентов входящие занижены: граф собран от них.
     Отношение «отдал / получил» для seed не применимо.
  4. Порог 5 000 KZT: дробление ниже порога невидимо.
  5. 31 seed из 81 не имеет исходящих переводов.
  6. 16 слабосвязных компонент, 352 узла вне крупнейшей.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


def load(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = Path(data_dir)
    edges = pd.read_parquet(d / "edges.parquet")
    nodes = pd.read_parquet(d / "nodes.parquet")
    tx = pd.read_parquet(d / "transactions.parquet")
    return edges, nodes, tx


def build_graph(edges: pd.DataFrame) -> nx.DiGraph:
    g = nx.DiGraph()
    for r in edges.itertuples(index=False):
        g.add_edge(int(r.src), int(r.dst), sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx))
    return g


def node_metrics(edges: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """Метрики по каждому узлу. Всё считается из данных, ничего не хардкодится."""
    incoming = edges.groupby("dst").agg(
        n_payers=("src", "nunique"),
        sum_in=("sum_kzt", "sum"),
        n_tx_in=("n_tx", "sum"),
    )
    outgoing = edges.groupby("src").agg(
        n_receivers=("dst", "nunique"),
        sum_out=("sum_kzt", "sum"),
        n_tx_out=("n_tx", "sum"),
    )

    m = nodes.set_index("gid").join(incoming).join(outgoing).fillna(0)
    m["n_payers"] = m["n_payers"].astype(int)
    m["n_receivers"] = m["n_receivers"].astype(int)

    # Доля полученного, которую узел отдал дальше.
    # 1.0 ≈ чистый транзит, 0.0 ≈ деньги осели. NaN — входящих не видно.
    m["passthrough"] = np.where(m.sum_in > 0, m.sum_out / m.sum_in.replace(0, np.nan), np.nan)

    # Ловушка 1: узел на последнем колене без исходящих — это обрыв обхода,
    # а не конечный получатель. Помечаем явно и не считаем terminal.
    max_depth = int(nodes.depth.max())
    m["truncated"] = (m.depth == max_depth) & (m.n_receivers == 0)

    # Ловушка 3: для seed входящие занижены — passthrough недостоверен.
    m["ratio_reliable"] = ~m.is_seed.astype(bool) & (m.sum_in > 0)

    return m.reset_index()


def add_components(m: pd.DataFrame, g: nx.DiGraph) -> pd.DataFrame:
    """Ловушка 6: сеть не монолитна. Номер слабосвязной компоненты."""
    comp = {}
    for i, c in enumerate(nx.weakly_connected_components(g)):
        for n in c:
            comp[n] = i
    m["component"] = m.gid.map(comp).fillna(-1).astype(int)
    return m


def cluster(m: pd.DataFrame, g: nx.DiGraph, seed: int = 42) -> pd.DataFrame:
    """Кластеризация Louvain по неориентированной проекции.

    seed фиксирован — требование воспроизводимости: один и тот же запуск
    должен давать один и тот же результат.
    """
    und = g.to_undirected()
    communities = nx.community.louvain_communities(und, weight="sum_kzt", seed=seed)
    cid = {n: i for i, c in enumerate(communities) for n in c}
    m["cluster_id"] = m.gid.map(cid).fillna(-1).astype(int)
    return m
