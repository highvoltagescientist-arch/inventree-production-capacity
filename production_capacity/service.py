"""InvenTree model adapter; no changes to core models or custom tables."""

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal

from build.models import BuildItem, BuildLine
from build.status_codes import BuildStatusGroups
from django.db.models import Q, Sum
from django.utils import timezone
from order.models import PurchaseOrderLineItem
from order.status_codes import PurchaseOrderStatus
from stock.models import StockItem

from .engine import CalculationError, Edge, Engine, Node, number

METADATA_KEY = "production_capacity"


def minimum_for(part):
    """Read only our metadata namespace and validate malformed stored values."""
    if part.metadata is not None and not isinstance(part.metadata, dict):
        raise CalculationError("Invalid part metadata")
    data = part.get_metadata(METADATA_KEY, {})
    if not isinstance(data, dict):
        raise CalculationError("Invalid production_capacity metadata")
    return data.get("minimum", 0)


def snapshot(root):
    """Read effective BOMs, then bulk-load stock, allocations and commitments.

    Exact part identities avoid counting variant inventory under both a parent
    and child part. Alternative parts are intentionally not optimized in v0.1.
    """
    nodes = {}
    pending = [root]
    warnings = set()
    while pending:
        part = pending.pop()
        if part.pk in nodes:
            continue
        if len(nodes) >= 5000:
            raise CalculationError("BOM exceeds the 5000-part planning limit")
        edges = []
        if part.assembly or part.virtual:
            for line in part.get_bom_items().select_related("sub_part"):
                if line.optional or line.is_consumable:
                    warnings.add(
                        "任意部品・消耗品は標準製造割当と同様に計算対象外です。"
                    )
                    continue
                edges.append(
                    Edge(
                        child=line.sub_part_id,
                        quantity=line.quantity,
                        piece_count=line.piece_count,
                        attrition=line.attrition,
                        setup=line.setup_quantity,
                        rounding=line.rounding_multiple or 0,
                    )
                )
                pending.append(line.sub_part)
                if line.allow_variants or line.substitutes.exists():
                    warnings.add(
                        "代替品・バリアント在庫は含めず、BOM指定部品だけで計算します。"
                    )
        if not part.active:
            raise CalculationError(f"Inactive part in BOM: {part.pk}")
        if part.virtual and not edges:
            raise CalculationError(f"Virtual part has no required BOM: {part.pk}")
        nodes[part.pk] = Node(
            id=part.pk,
            name=part.name,
            ipn=part.IPN or "",
            assembly=part.assembly or part.virtual,
            integral=not part.virtual,
            bom=tuple(edges),
        )

    items = list(
        StockItem.objects.filter(StockItem.IN_STOCK_FILTER, part_id__in=nodes)
        .filter(Q(location__external=False) | Q(location=None))
        .only("pk", "part_id", "quantity")
    )
    allocations = StockItem.bulk_allocation_count(items)
    stocks = defaultdict(Decimal)
    reserved = defaultdict(Decimal)
    for item in items:
        reserved[item.part_id] += min(
            number(item.quantity), number(allocations.get(item.pk, 0))
        )
        stocks[item.part_id] += max(
            Decimal(0), number(item.quantity) - number(allocations.get(item.pk, 0))
        )

    incoming = defaultdict(Decimal)
    # PENDING is a draft; ON_HOLD has no reliable incoming commitment.
    lines = PurchaseOrderLineItem.objects.filter(
        part__part_id__in=nodes,
        order__status=PurchaseOrderStatus.PLACED.value,
    ).select_related("part")
    for line in lines:
        remaining = max(Decimal(0), number(line.quantity) - number(line.received))
        incoming[line.part.part_id] += number(line.part.base_quantity(remaining))

    scheduled = defaultdict(Decimal)
    build_lines = list(
        BuildLine.objects.filter(
            build__status__in=BuildStatusGroups.ACTIVE_CODES,
            bom_item__sub_part_id__in=nodes,
        ).select_related("bom_item")
    )
    allocated_by_line = {
        row["build_line"]: row["total"]
        for row in BuildItem.objects.filter(build_line__in=build_lines)
        .values("build_line")
        .annotate(total=Sum("quantity"))
    }
    for line in build_lines:
        scheduled[line.bom_item.sub_part_id] += max(
            Decimal(0),
            number(line.quantity)
            - number(line.consumed)
            - number(allocated_by_line.get(line.pk, 0)),
        )
    for key, node in nodes.items():
        nodes[key] = replace(
            node,
            stock=stocks[key],
            allocated=reserved[key],
            incoming=incoming[key],
            scheduled=scheduled[key],
        )
    return Engine(nodes, root.pk), sorted(warnings)


def calculate(part):
    """Always recalculate; no stale cache after stock or BOM changes."""
    engine, warnings = snapshot(part)
    result = engine.report(minimum_for(part))
    result.update(
        {
            "warnings": warnings,
            "calculated_at": timezone.now().isoformat(),
            "can_edit_minimum": False,
        }
    )
    return result
