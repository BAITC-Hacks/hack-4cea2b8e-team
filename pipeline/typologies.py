"""Детекторы известных AML-типологий.

Роли в pipeline/roles.py отвечают на вопрос «кто этот узел в сети».
Типологии здесь отвечают на другой: «какое отмывочное поведение видно
в его транзакциях». Два независимых сигнала, вместе дают обоснование,
понятное AML-аналитику.

Названия взяты не из головы — это стандартный словарь индустрии:

  structuring / smurfing  дробление крупной суммы на много мелких переводов,
                          сходящихся в одну точку (Linkurious, TigerGraph)
  layering                сквозной транзит через цепочку счетов; деньги
                          не задерживаются (TigerGraph)
  round-tripping          средства возвращаются к отправителю по циклу
                          (Linkurious)
  reconvergence           несколько путей сходятся обратно в один счёт
                          (TigerGraph)
  synchronized inflow     скоординированные поступления от нескольких
                          плательщиков в один день

Ограничение данных: порог выгрузки 5 000 ₸ — дробление ниже него невидимо.
Это оговаривается в README и в обосновании.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from .roles import THRESHOLDS

PARAMS = THRESHOLDS  # Совместимый псевдоним; настройки хранятся в одном месте.


def structuring(tx: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Дробление: много близких по размеру переводов между одной парой за короткий срок.

    Возвращает по получателю: сколько таких пар на него замкнуто и общая сумма.
    """
    t = tx.copy()
    t["date"] = pd.to_datetime(t["date"])
    g = t.groupby(["src", "dst"]).agg(
        n=("sum_kzt", "size"),
        total=("sum_kzt", "sum"),
        mean=("sum_kzt", "mean"),
        std=("sum_kzt", "std"),
        first=("date", "min"),
        last=("date", "max"),
    ).reset_index()

    g["cv"] = (g["std"] / g["mean"]).fillna(0)          # коэффициент вариации сумм
    g["span"] = (g["last"] - g["first"]).dt.days

    flagged = g[
        (g.n >= p["structuring_min_tx"])
        & (g.cv <= p["structuring_max_cv"])
        & (g.span <= p["structuring_window_days"])
    ]

    return (
        flagged.groupby("dst")
        .agg(structuring_pairs=("src", "nunique"),
             structuring_sum=("total", "sum"),
             structuring_tx=("n", "sum"))
        .reset_index()
        .rename(columns={"dst": "gid"})
    )


def rapid_passthrough(tx: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Layering: узел получил и в течение окна отдал большую часть дальше."""
    t = tx.copy()
    t["date"] = pd.to_datetime(t["date"])

    inflow = t.groupby(["dst", "date"]).sum_kzt.sum().rename("got").reset_index()
    inflow = inflow.rename(columns={"dst": "gid"})
    outflow = t.groupby(["src", "date"]).sum_kzt.sum().rename("sent").reset_index()
    outflow = outflow.rename(columns={"src": "gid"})

    w = pd.Timedelta(days=p["passthrough_window_days"])
    rows = []
    for gid, ins in inflow.groupby("gid"):
        outs = outflow[outflow.gid == gid]
        if outs.empty:
            continue
        matched = 0.0
        # Сопоставляем наблюдаемые суммы по FIFO, не расходуя исходящую сумму дважды.
        # Время внутри дня неизвестно: это совместимость по датам, не трассировка денег.
        outs = outs.sort_values("date")
        dates = outs.date.tolist()
        available = outs.sent.astype(float).tolist()
        for r in ins.sort_values("date").itertuples(index=False):
            remaining = float(r.got)
            for i, date in enumerate(dates):
                if date < r.date or date > r.date + w or available[i] <= 0:
                    continue
                amount = min(remaining, available[i])
                available[i] -= amount
                remaining -= amount
                matched += amount
                if remaining <= 0:
                    break
        total_in = ins.got.sum()
        if total_in > 0 and matched / total_in >= p["passthrough_min_share"]:
            rows.append({"gid": gid, "rapid_share": round(matched / total_in, 3),
                         "rapid_sum": round(matched)})
    return pd.DataFrame(rows, columns=["gid", "rapid_share", "rapid_sum"])


def synchronized_inflow(tx: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Скоординированные поступления: несколько разных плательщиков в один день."""
    t = tx.copy()
    t["date"] = pd.to_datetime(t["date"])
    d = t.groupby(["dst", "date"]).agg(payers=("src", "nunique"),
                                       amount=("sum_kzt", "sum")).reset_index()
    hit = d[d.payers >= p["sync_min_payers"]]
    return (
        hit.groupby("dst")
        .agg(sync_days=("date", "nunique"),
             sync_max_payers=("payers", "max"),
             sync_sum=("amount", "sum"))
        .reset_index()
        .rename(columns={"dst": "gid"})
    )


def round_tripping(g: nx.DiGraph, p: dict = PARAMS) -> pd.DataFrame:
    """Возвратные потоки: деньги возвращаются к отправителю по короткому циклу."""
    counts: dict[int, int] = {}
    try:
        for cycle in nx.simple_cycles(g, length_bound=p["cycle_max_len"]):
            if len(cycle) < 2:
                continue
            for n in cycle:
                counts[n] = counts.get(n, 0) + 1
    except TypeError:
        # networkx < 3.1 не знает length_bound — пропускаем, не роняя пайплайн
        pass
    return pd.DataFrame(
        {"gid": list(counts), "cycles": list(counts.values())},
        columns=["gid", "cycles"],
    )


def resilience(g: nx.DiGraph, top_gids: list[int]) -> dict:
    """Устойчивость сети: что станет, если изъять топ-N узлов.

    Аргумент для аналитика: стоит ли начинать именно с них.
    """
    before_components = nx.number_weakly_connected_components(g)
    before_largest = max((len(c) for c in nx.weakly_connected_components(g)), default=0)

    h = g.copy()
    h.remove_nodes_from([n for n in top_gids if n in h])

    after_components = nx.number_weakly_connected_components(h)
    after_largest = max((len(c) for c in nx.weakly_connected_components(h)), default=0)

    return {
        "removed": len([n for n in top_gids if n in g]),
        "components_before": before_components,
        "components_after": after_components,
        "largest_before": before_largest,
        "largest_after": after_largest,
        "largest_drop_pct": round(100 * (1 - after_largest / before_largest), 1)
        if before_largest
        else 0.0,
    }


def attach(m: pd.DataFrame, tx: pd.DataFrame, g: nx.DiGraph) -> pd.DataFrame:
    """Присоединяет все типологии к таблице метрик и формирует текстовую метку."""
    for part in (structuring(tx), rapid_passthrough(tx), synchronized_inflow(tx), round_tripping(g)):
        if not part.empty:
            m = m.merge(part, on="gid", how="left")

    for col, default in [
        ("structuring_pairs", 0), ("structuring_sum", 0), ("structuring_tx", 0),
        ("rapid_share", 0.0), ("rapid_sum", 0),
        ("sync_days", 0), ("sync_max_payers", 0), ("sync_sum", 0),
        ("cycles", 0),
    ]:
        if col not in m.columns:
            m[col] = default
        m[col] = m[col].fillna(default)

    def label(r) -> str:
        tags = []
        if r.structuring_pairs >= 1:
            tags.append("structuring")
        if r.rapid_share >= PARAMS["passthrough_min_share"]:
            tags.append("layering")
        if r.sync_days >= 1:
            tags.append("synchronized-inflow")
        if r.cycles >= 1:
            tags.append("round-tripping")
        return "|".join(tags)

    m["typologies"] = m.apply(label, axis=1)
    return m


def describe(r: pd.Series) -> str:
    """Человеческая расшифровка типологий узла — идёт в evidence и в карточку."""
    parts = []
    if r.get("structuring_pairs", 0) >= 1:
        parts.append(
            f"дробление: {int(r.structuring_tx)} близких по размеру переводов "
            f"от {int(r.structuring_pairs)} плательщиков"
        )
    if r.get("rapid_share", 0) >= PARAMS["passthrough_min_share"]:
        parts.append(f"возможный транзит: {r.rapid_share:.0%} поступлений сопоставлены по датам за "
                     f"{PARAMS['passthrough_window_days']} дней")
    if r.get("sync_days", 0) >= 1:
        parts.append(f"синхронные поступления: до {int(r.sync_max_payers)} плательщиков "
                     f"в один день, {int(r.sync_days)} раз")
    if r.get("cycles", 0) >= 1:
        parts.append(f"участвует в {int(r.cycles)} циклах связей; возврат тех же денег не доказан")
    return "; ".join(parts)
