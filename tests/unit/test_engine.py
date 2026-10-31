"""Capacity invariants independent of Django or an InvenTree installation."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from production_capacity.engine import (
    MAX_CAPACITY,
    CalculationError,
    Edge,
    Engine,
    Node,
)


def edge(child, quantity=1, **kwargs):
    return Edge(child, quantity, **kwargs)


def node(key, *, stock=0, incoming=0, scheduled=0, bom=(), **kwargs):
    return Node(
        key,
        name=f"Part {key}",
        stock=stock,
        incoming=incoming,
        scheduled=scheduled,
        assembly=bool(bom),
        integral=True,
        bom=tuple(bom),
        **kwargs,
    )


def test_single_level_and_completed_root_is_excluded():
    engine = Engine(
        {
            1: node(1, stock=1000, bom=[edge(2, 3), edge(3, 2)]),
            2: node(2, stock=16),
            3: node(3, stock=9),
        },
        1,
    )
    assert engine.capacity() == (4, False)


def test_multilevel_materials_can_build_unstocked_subassembly():
    engine = Engine(
        {
            1: node(1, bom=[edge(2, 2)]),
            2: node(2, bom=[edge(3, 3)]),
            3: node(3, stock=30),
        },
        1,
    )
    assert engine.capacity()[0] == 5
    assert engine.report(5)["manufacturing_suggestions"][0]["quantity"] == "10"
    assert engine.report(5)["manufacturing_suggestions"][0]["materials_ready"]


def test_subassembly_stock_used_before_its_materials():
    engine = Engine(
        {
            1: node(1, bom=[edge(2, 2)]),
            2: node(2, stock=5, bom=[edge(3, 3)]),
            3: node(3, stock=9),
        },
        1,
    )
    assert engine.capacity()[0] == 4


def test_common_raw_material_across_multiple_levels():
    engine = Engine(
        {
            1: node(1, bom=[edge(2), edge(3), edge(4)]),
            2: node(2, bom=[edge(4, 2)]),
            3: node(3, bom=[edge(4, 3)]),
            4: node(4, stock=25),
        },
        1,
    )
    assert engine.capacity()[0] == 4  # six per product, not min(25, 12, 8)
    assert engine.report(5)["purchase_shortages"][0]["quantity"] == "5"


def test_material_limits_show_every_constraint_independent_of_warning_minimum():
    engine = Engine(
        {
            1: node(1, bom=[edge(2), edge(3, 5)]),
            2: node(2, stock=0),
            3: node(3, stock=30),
        },
        1,
    )
    limits = engine.report(0)["material_limits"]
    assert [(row["part"], row["capacity"]) for row in limits] == [(2, 0), (3, 6)]
    assert engine.report(100)["material_limits"] == limits
    assert engine.report(0)["current_capacity"] == 0


def test_material_limit_uses_shared_demand_stocked_subassembly_and_setup():
    engine = Engine(
        {
            1: node(1, bom=[edge(2), edge(3, 2), edge(4)]),
            2: node(2, stock=2, bom=[edge(3, 3, setup=D(1))]),
            3: node(3, stock=30),
            4: node(4, stock=0),
        },
        1,
    )
    limits = engine.report()["material_limits"]
    assert [(row["part"], row["capacity"]) for row in limits] == [(4, 0), (3, 7)]
    assert engine.plan(7).demand[3] == 30
    assert engine.plan(8).demand[3] == 35


def test_material_limit_respects_rounding_instead_of_simple_division():
    engine = Engine(
        {1: node(1, bom=[edge(2, "0.5", rounding=D(2))]), 2: node(2, stock=5)},
        1,
    )
    assert engine.report()["material_limits"][0]["capacity"] == 8


def test_shared_assembly_aggregates_demand_before_rounding_and_setup():
    engine = Engine(
        {
            1: node(1, bom=[edge(2), edge(3)]),
            2: node(2, bom=[edge(4)]),
            3: node(3, bom=[edge(4)]),
            4: node(4, stock=1, bom=[edge(5, setup=D(2))]),
            5: node(5, stock=9),
        },
        1,
    )
    assert engine.capacity()[0] == 4  # seven newly built + one setup of two
    assert engine.plan(4).manufacture[4] == 7


def test_shared_stock_is_not_dependent_on_bom_line_order():
    nodes = {
        1: node(1, bom=[edge(2), edge(4)]),
        2: node(2, bom=[edge(3)]),
        3: node(3, stock=2, bom=[edge(4, 2)]),
        4: node(4, stock=10),
    }
    expected = Engine(nodes, 1).capacity()
    nodes[1] = replace(nodes[1], bom=tuple(reversed(nodes[1].bom)))
    assert expected == Engine(nodes, 1).capacity() == (4, False)


def test_incoming_is_not_immediate_and_scheduled_demand_is_reserved_first():
    engine = Engine(
        {1: node(1, bom=[edge(2, 2)]), 2: node(2, stock=10, incoming=10, scheduled=6)},
        1,
    )
    result = engine.report(4)
    assert result["current_capacity"] == 2
    assert result["future_capacity"] == 7
    assert result["shortfall"] == 2 and result["status"] == "warning"
    assert result["purchase_shortages"][0]["incoming"] == "10"


def test_commitments_exceed_stock_and_reserve_incoming_too():
    engine = Engine(
        {1: node(1, bom=[edge(2)]), 2: node(2, stock=2, incoming=10, scheduled=7)}, 1
    )
    assert engine.capacity()[0] == 0
    assert engine.capacity(future=True)[0] == 5


def test_lower_level_purchase_shortage_blocks_manufacturing_suggestion():
    engine = Engine(
        {1: node(1, bom=[edge(2)]), 2: node(2, bom=[edge(3, 2)]), 3: node(3, stock=4)},
        1,
    )
    report = engine.report(5)
    assert report["purchase_shortages"][0]["part"] == 3
    assert report["purchase_shortages"][0]["required"] == "10"
    assert report["purchase_shortages"][0]["quantity"] == "6"
    assert not report["manufacturing_suggestions"][0]["materials_ready"]


def test_no_warning_at_minimum_and_zero_minimum_has_no_target_requirements():
    engine = Engine({1: node(1, bom=[edge(2)]), 2: node(2, stock=10)}, 1)
    assert engine.report(10)["status"] == "ok"
    assert engine.report(0)["purchase_shortages"] == []
    assert engine.report(0)["manufacturing_suggestions"] == []


def test_piece_count_attrition_setup_and_rounding_match_batch_semantics():
    line = edge(
        2, "0.1", piece_count=D(2), attrition=D(10), setup=D("0.25"), rounding=D("0.5")
    )
    assert line.required(D(5)) == D("1.5")
    assert line.required(D(0)) == 0
    engine = Engine({1: node(1, bom=[line]), 2: node(2, stock="1.5")}, 1)
    assert engine.capacity()[0] == 5


def test_fractional_subassembly_requirement_rounds_up_to_complete_units():
    engine = Engine(
        {
            1: node(1, bom=[edge(2, "0.5")]),
            2: node(2, bom=[edge(3, 3)]),
            3: node(3, stock=5),
        },
        1,
    )
    assert engine.capacity()[0] == 2


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity", "bad", None])
def test_invalid_stock_rejected(value):
    with pytest.raises(CalculationError):
        node(1, stock=value)


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity", "invalid"])
def test_invalid_bom_quantity_rejected(value):
    with pytest.raises(CalculationError):
        edge(2, value)


@pytest.mark.parametrize("minimum", [-1, "NaN", "2.5", MAX_CAPACITY + 1])
def test_invalid_minimum_rejected(minimum):
    engine = Engine({1: node(1, bom=[edge(2)]), 2: node(2)}, 1)
    with pytest.raises(CalculationError):
        engine.report(minimum)


def test_cycle_rejected_even_when_subassembly_is_stocked():
    with pytest.raises(CalculationError, match="Circular"):
        Engine({1: node(1, bom=[edge(2)]), 2: node(2, stock=100, bom=[edge(1)])}, 1)


def test_missing_part_and_empty_root_fail_safely():
    with pytest.raises(CalculationError, match="Missing"):
        Engine({1: node(1, bom=[edge(2)])}, 1)
    with pytest.raises(CalculationError, match="no manufacturable"):
        Engine({1: node(1)}, 1)


def test_capacity_limit_is_explicit_lower_bound():
    engine = Engine({1: node(1, bom=[edge(2)]), 2: node(2, stock=MAX_CAPACITY * 2)}, 1)
    assert engine.capacity() == (MAX_CAPACITY, True)
    assert engine.report()["capacity_capped"]


def test_large_dag_does_not_use_python_recursion():
    nodes = {k: node(k, bom=[edge(k + 1)]) for k in range(1, 1500)}
    nodes[1500] = node(1500, stock=15)
    assert Engine(nodes, 1).capacity()[0] == 15


def test_shared_material_capacity_against_closed_form_for_many_stock_levels():
    for assembly_stock in range(5):
        for raw_stock in range(20):
            engine = Engine(
                {
                    1: node(1, bom=[edge(2), edge(3, 2)]),
                    2: node(2, stock=assembly_stock, bom=[edge(3, 3)]),
                    3: node(3, stock=raw_stock),
                },
                1,
            )
            expected = max(
                q
                for q in range(20)
                if 2 * q + 3 * max(0, q - assembly_stock) <= raw_stock
            )
            assert engine.capacity()[0] == expected


def test_purchase_shortage_targets_minimum_through_subassembly():
    engine = Engine(
        {
            1: node(1, bom=[edge(2)]),
            2: node(2, stock=2, bom=[edge(3, 3)]),
            3: node(3, stock=10),
        },
        1,
    )
    result = engine.report(6)
    assert D(result["purchase_shortages"][0]["quantity"]) == 2
    assert D(result["purchase_shortages"][0]["required"]) == 12
    assert D(result["manufacturing_suggestions"][0]["quantity"]) == 4
    assert "bottlenecks" not in result


def test_report_keeps_physical_stock_allocated_and_scheduled_separate():
    engine = Engine(
        {1: node(1, bom=[edge(2)]), 2: node(2, stock=7, scheduled=2, allocated=D(3))}, 1
    )
    row = engine.report(10)["purchase_shortages"][0]
    assert row["stock"] == "10" and row["allocated"] == "3"
    assert row["available"] == "5" and row["scheduled"] == "2"
