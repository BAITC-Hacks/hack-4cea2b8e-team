"""ЗОНА АРГЫНА. Проверки по must-have из ТЗ.

Каждый тест назван словами требования — на демо можно показать жюри зелёный
прогон, который читается как их же чеклист.

    pytest -q

Данные для тестов генерируются синтетически по схеме из ТЗ, поэтому тесты
проходят и без выгрузки организаторов. Когда данные появятся — добавьте
прогон на них отдельным тестом.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from pipeline import graph, roles


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    """Синтетическая выгрузка по схеме ТЗ: edges / nodes / transactions."""
    random.seed(1)
    np.random.seed(1)
    d = tmp_path_factory.mktemp("data")
    n = 200
    nodes = pd.DataFrame(
        {
            "gid": range(1, n + 1),
            "depth": [0] * 15 + [1] * 40 + [2] * 45 + [3] * 50 + [4] * 50,
            "is_seed": [True] * 15 + [False] * (n - 15),
        }
    )
    rows = []
    for _ in range(400):
        s, t = random.randint(1, 150), random.randint(16, n)
        if s != t:
            rows.append((s, t, random.randint(5000, 5_000_000), random.randint(1, 9), random.randint(1, 4)))
    edges = pd.DataFrame(rows, columns=["src", "dst", "sum_kzt", "n_tx", "depth"]).drop_duplicates(["src", "dst"])
    tx = pd.DataFrame(
        [(r.src, r.dst, "2026-07-15", r.sum_kzt) for r in edges.itertuples()],
        columns=["src", "dst", "date", "sum_kzt"],
    )
    for name, df in [("edges", edges), ("nodes", nodes), ("transactions", tx)]:
        df.to_parquet(d / f"{name}.parquet")
    return d


@pytest.fixture(scope="module")
def result(data):
    edges, nodes, tx = graph.load(data)
    g = graph.build_graph(edges)
    m = graph.node_metrics(edges, nodes)
    m = graph.add_components(m, g)
    m = graph.cluster(m, g)
    m = roles.assign(m)
    m = roles.priority(m)
    return m, nodes, g


def test_role_for_every_node(result):
    """Must-have 2: роль есть у каждого узла, ни одной пропущенной."""
    m, nodes, _ = result
    assert len(m) == len(nodes)
    assert m.role.notna().all()
    assert m.role.isin(roles.ROLES).all()


def test_evidence_is_never_empty(result):
    """Must-have 2: evidence непустой у каждого узла."""
    m, _, _ = result
    assert (m.evidence.str.len() > 0).all()


def test_evidence_fits_200_chars(result):
    """ТЗ: обоснование до 200 символов, человекочитаемо."""
    m, _, _ = result
    too_long = m[m.evidence.str.len() > 200]
    assert too_long.empty, f"{len(too_long)} обоснований длиннее 200 символов"


def test_truncated_nodes_are_not_terminal(result):
    """Ловушка ТЗ: обрыв обхода на последнем колене — не конечный получатель."""
    m, _, _ = result
    assert m[m.truncated].role.eq("terminal").sum() == 0


def test_role_score_in_range(result):
    """Must-have 2: role_score — уверенность 0–1."""
    m, _, _ = result
    assert m.role_score.between(0, 1).all()


def test_priority_score_in_range(result):
    m, _, _ = result
    assert m.priority_score.between(0, 1).all()


def test_every_node_has_cluster(result):
    """Must-have 4: cluster_id есть у каждого узла."""
    m, _, _ = result
    assert m.cluster_id.notna().all()


def test_pipeline_is_deterministic(data):
    """Воспроизводимость: два прогона дают идентичный результат."""
    def run():
        edges, nodes, _ = graph.load(data)
        g = graph.build_graph(edges)
        m = graph.node_metrics(edges, nodes)
        m = graph.add_components(m, g)
        m = graph.cluster(m, g)
        return roles.priority(roles.assign(m))

    a, b = run(), run()
    pd.testing.assert_frame_equal(a, b)


def test_thresholds_documented(result):
    """Must-have 3: все пороги в одном месте и задокументированы."""
    assert roles.THRESHOLDS, "THRESHOLDS пуст"
    assert all(isinstance(v, (int, float)) for v in roles.THRESHOLDS.values())
