"""Присвоение ролей узлам.

Must-have №3 из ТЗ: «Критерии ролей задокументированы и объяснимы. Для каждой
роли — формальное правило или метрика с порогом». Жюри назовёт три
произвольных gid и попросит за минуту объяснить, почему роль именно такая.

Поэтому:
  * все пороги собраны в THRESHOLDS — одно место, которое показываем жюри;
  * каждое правило возвращает evidence — человекочитаемое обоснование
    до 200 символов с конкретными числами из данных;
  * «чёрный ящик» запрещён ТЗ: роль без объяснимого правила не засчитывается.

Формулировки осторожные: «признаки консолидации», а не «организатор».
ТЗ требует подавать выводы как гипотезы для проверки.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# ПОРОГИ. Подобрать по реальному распределению после первого прогона —
# см. scripts/explore.py. Здесь стартовые значения из описания данных в ТЗ.
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "consolidator_min_payers": 8,      # в данных есть узлы с 8–24 плательщиками
    "consolidator_max_passthrough": 0.5,
    "distributor_min_receivers": 20,   # есть узлы с веером на 60–116 получателей
    "transit_passthrough_lo": 0.8,     # 72 узла с коэффициентом пропуска 0.8–1.2
    "transit_passthrough_hi": 1.2,
    "terminal_max_passthrough": 0.1,
    "terminal_min_sum_in": 1_000_000,
    "coordinator_min_payers": 5,
    "coordinator_min_receivers": 5,
}

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def classify(row: pd.Series, t: dict = THRESHOLDS) -> tuple[str, float, str]:
    """Возвращает (роль, уверенность 0–1, обоснование).

    Порядок проверок важен: более специфичные роли идут раньше.
    """
    payers, receivers = int(row.n_payers), int(row.n_receivers)
    pt = row.passthrough if pd.notna(row.passthrough) else None

    # Ловушка 1: обрыв обхода на последнем колене.
    # Такой узел НЕ конечный получатель — мы просто не видим, что было дальше.
    if row.truncated:
        return (
            "peripheral",
            0.2,
            f"Узел на последнем колене выгрузки, исходящие переводы за границей "
            f"обхода не видны. Получает от {payers} плательщиков. Роль не определена: "
            f"нужна выгрузка на колено глубже.",
        )

    # Координирующий узел: и собирает, и раздаёт широко.
    if payers >= t["coordinator_min_payers"] and receivers >= t["coordinator_min_receivers"]:
        return (
            "coordinator",
            0.7,
            f"Одновременно принимает от {payers} плательщиков и отправляет "
            f"{receivers} получателям — признаки узла, связывающего части сети.",
        )

    # Точка консолидации: много плательщиков, удерживает значимую часть.
    if payers >= t["consolidator_min_payers"] and (
        pt is None or pt <= t["consolidator_max_passthrough"]
    ):
        held = f", дальше уходит {pt:.0%} полученного" if pt is not None else ""
        return (
            "consolidator",
            0.8,
            f"Принимает от {payers} разных плательщиков на {_fmt(row.sum_in)} ₸{held}. "
            f"Признаки точки аккумулирования средств.",
        )

    # Веерное распределение.
    if receivers >= t["distributor_min_receivers"]:
        return (
            "distributor",
            0.8,
            f"Отправляет {receivers} получателям на {_fmt(row.sum_out)} ₸. "
            f"Признаки веерного распределения средств.",
        )

    # Транзит: пропускает почти всё, что получил.
    if pt is not None and row.ratio_reliable and t["transit_passthrough_lo"] <= pt <= t["transit_passthrough_hi"]:
        return (
            "transit",
            0.75,
            f"Пропускает {pt:.0%} полученного дальше ({_fmt(row.sum_in)} ₸ получено, "
            f"{_fmt(row.sum_out)} ₸ отправлено). Признаки транзитного счёта.",
        )

    # Конечный получатель: деньги пришли и остались. Только для узлов,
    # где обрыв обхода исключён и отношение достоверно.
    if (
        pt is not None
        and row.ratio_reliable
        and pt <= t["terminal_max_passthrough"]
        and row.sum_in >= t["terminal_min_sum_in"]
    ):
        return (
            "terminal",
            0.75,
            f"Получил {_fmt(row.sum_in)} ₸ от {payers} плательщиков, дальше отправил "
            f"{pt:.0%}. Средства остаются на узле.",
        )

    return (
        "peripheral",
        0.3,
        f"Плательщиков {payers}, получателей {receivers}, оборот "
        f"{_fmt(row.sum_in + row.sum_out)} ₸ — устойчивых признаков роли не выявлено.",
    )


def assign(m: pd.DataFrame) -> pd.DataFrame:
    out = m.apply(lambda r: pd.Series(classify(r), index=["role", "role_score", "evidence"]), axis=1)
    return pd.concat([m, out], axis=1)


def priority(m: pd.DataFrame) -> pd.DataFrame:
    """Приоритет проверки для аналитика, 0–1.

    Смысл: смотреть в первую очередь на тех, кто собирает деньги со многих
    и распоряжается большими суммами, а не на 81 «курьера» из исходного списка.
    """
    role_weight = {
        "coordinator": 1.0,
        "consolidator": 0.9,
        "distributor": 0.7,
        "transit": 0.5,
        "terminal": 0.6,
        "peripheral": 0.1,
    }
    turnover = m.sum_in + m.sum_out
    norm = turnover / turnover.max() if turnover.max() else turnover
    reach = (m.n_payers + m.n_receivers) / (m.n_payers + m.n_receivers).max()

    m["priority_score"] = (
        0.5 * m.role.map(role_weight).fillna(0.1)
        + 0.3 * norm
        + 0.2 * reach
    ).round(4)
    return m
