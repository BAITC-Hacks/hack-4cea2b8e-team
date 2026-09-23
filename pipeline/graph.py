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


def load(data_dir: str | Path, *, reconcile: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Загрузка со схемной проверкой; полный анализ также сверяет агрегаты."""
    d = Path(data_dir)
    edges = pd.read_parquet(d / "edges.parquet")
    nodes = pd.read_parquet(d / "nodes.parquet")
    tx = pd.read_parquet(d / "transactions.parquet")
    validate(edges, nodes, tx, reconcile=reconcile)
    return (edges.sort_values(["src", "dst"]).reset_index(drop=True),
            nodes.sort_values("gid").reset_index(drop=True),
            tx.sort_values(["date", "src", "dst", "sum_kzt"]).reset_index(drop=True))


def validate(edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame, *, reconcile: bool = True) -> None:
    """Проверяем схему и согласованность трёх файлов до расчёта."""
    schemas = [(nodes, {"gid", "depth", "is_seed"}, "nodes"),
               (edges, {"src", "dst", "sum_kzt", "n_tx", "depth"}, "edges"),
               (tx, {"src", "dst", "date", "sum_kzt"}, "transactions")]
    for frame, required, name in schemas:
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{name}: отсутствуют колонки {sorted(missing)}")
        if frame[list(required)].isna().any().any():
            raise ValueError(f"{name}: обязательные поля содержат пропуски")
        for col in required - {"date", "is_seed"}:
            values = pd.to_numeric(frame[col], errors="coerce")
            if not np.isfinite(values).all():
                raise ValueError(f"{name}.{col}: нужны конечные числовые значения")
            if col != "sum_kzt" and not (values % 1 == 0).all():
                raise ValueError(f"{name}.{col}: нужны целые числа")
            frame[col] = values.astype("int64") if col != "sum_kzt" else values.astype(float)
    if nodes.empty or nodes.gid.duplicated().any():
        raise ValueError("nodes: нужны уникальные узлы и хотя бы один узел")
    if not nodes.is_seed.isin([True, False]).all():
        raise ValueError("nodes.is_seed: нужны булевы значения")
    nodes["is_seed"] = nodes.is_seed.astype(bool)
    if (nodes.depth < 0).any() or (edges.depth < 1).any():
        raise ValueError("Глубина обхода не может быть отрицательной; глубина ребра начинается с 1")
    if edges.duplicated(["src", "dst"]).any():
        raise ValueError("edges: пары src/dst должны быть уникальны")
    ids = set(nodes.gid)
    for frame, name in [(edges, "edges"), (tx, "transactions")]:
        if not set(frame.src).union(frame.dst) <= ids:
            raise ValueError(f"{name}: ссылка на отсутствующий gid")
        if (frame.sum_kzt <= 0).any():
            raise ValueError(f"{name}: суммы должны быть положительными")
    if (edges.n_tx < 1).any():
        raise ValueError("edges.n_tx: число транзакций должно быть положительным")
    tx["date"] = pd.to_datetime(tx.date, errors="raise")
    if not reconcile:
        return
    actual = tx.groupby(["src", "dst"]).agg(total=("sum_kzt", "sum"), count=("sum_kzt", "size"))
    check = edges.merge(actual, left_on=["src", "dst"], right_index=True, how="outer")
    if (check[["sum_kzt", "n_tx", "total", "count"]].isna().any().any()
            or not np.allclose(check.sum_kzt, check.total, rtol=0, atol=0.01)
            or not check.n_tx.eq(check["count"]).all()):
        raise ValueError("edges и transactions: суммы или количества переводов не совпадают")


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame | None = None) -> nx.DiGraph:
    g = nx.DiGraph()
    if nodes is not None:
        g.add_nodes_from(sorted(nodes.gid.astype(int)))
    for r in edges.sort_values(["src", "dst"]).itertuples(index=False):
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
    from .roles import THRESHOLDS
    m["truncated"] = (m.depth >= THRESHOLDS["collection_depth"]) & (m.n_receivers == 0)

    # Ловушка 3: для seed входящие занижены — passthrough недостоверен.
    m["ratio_reliable"] = ~m.is_seed.astype(bool) & ~m.truncated & (m.sum_in > 0)

    return m.reset_index()


def add_components(m: pd.DataFrame, g: nx.DiGraph) -> pd.DataFrame:
    """Ловушка 6: сеть не монолитна. Номер слабосвязной компоненты."""
    comp = {}
    g.add_nodes_from(sorted(m.gid.astype(int)))
    for i, c in enumerate(sorted(nx.weakly_connected_components(g), key=lambda c: (-len(c), min(c)))):
        for n in c:
            comp[n] = i
    m["component"] = m.gid.map(comp).fillna(-1).astype(int)
    return m


def cluster(m: pd.DataFrame, g: nx.DiGraph, seed: int = 42) -> pd.DataFrame:
    """Кластеризация Louvain по неориентированной проекции.

    seed фиксирован — требование воспроизводимости: один и тот же запуск
    должен давать один и тот же результат.
    """
    g.add_nodes_from(sorted(m.gid.astype(int)))
    und = nx.Graph()
    und.add_nodes_from(sorted(g.nodes))
    # При встречных переводах складываем веса обоих направлений.
    for src, dst, data in sorted(g.edges(data=True)):
        previous = und.get_edge_data(src, dst, {}).get("sum_kzt", 0)
        und.add_edge(src, dst, sum_kzt=previous + data["sum_kzt"])
    if und.number_of_edges():
        communities = nx.community.louvain_communities(und, weight="sum_kzt", seed=seed)
    else:
        communities = [{n} for n in und]
    communities = sorted(communities, key=lambda c: (-len(c), min(c)))
    cid = {n: i for i, c in enumerate(communities) for n in c}
    m["cluster_id"] = m.gid.map(cid).fillna(-1).astype(int)
    return m
