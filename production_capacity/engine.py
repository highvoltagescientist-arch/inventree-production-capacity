"""Deterministic, stock-conserving capacity calculation for acyclic BOMs.

Demand is aggregated in parent-before-child topological order. Each assembly
is produced in one batch; finished assembly stock is used before manufacturing.
The root's finished stock is excluded: capacity means *additional* production.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, InvalidOperation

ZERO = Decimal(0)
MAX_CAPACITY = 1_000_000_000


class CalculationError(ValueError):
    """Invalid or unsupported planning input, never an optimistic capacity."""


def number(value, *, positive=False) -> Decimal:
    """Validate finite nonnegative decimal input without float conversion."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CalculationError(f"Invalid quantity: {value!r}") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise CalculationError(f"Invalid quantity: {value!r}")
    return result


@dataclass(frozen=True)
class Edge:
    """One BOM line, matching BomItem.get_required_quantity semantics."""

    child: int
    quantity: Decimal
    piece_count: Decimal = Decimal(1)
    attrition: Decimal = ZERO
    setup: Decimal = ZERO
    rounding: Decimal = ZERO

    def __post_init__(self):
        for name in ("quantity", "piece_count", "attrition", "setup", "rounding"):
            object.__setattr__(
                self,
                name,
                number(
                    getattr(self, name), positive=name in ("quantity", "piece_count")
                ),
            )

    def required(self, batch: Decimal) -> Decimal:
        if batch <= 0:
            return ZERO
        result = (
            self.quantity * self.piece_count * batch * (1 + self.attrition / 100)
            + self.setup
        )
        if self.rounding:
            result = (result / self.rounding).to_integral_value(
                rounding=ROUND_CEILING
            ) * self.rounding
        return result


@dataclass(frozen=True)
class Node:
    """A part and an immutable snapshot of its supplies and commitments."""

    id: int
    name: str = ""
    ipn: str = ""
    stock: Decimal = ZERO
    allocated: Decimal = ZERO
    incoming: Decimal = ZERO
    scheduled: Decimal = ZERO
    assembly: bool = False
    integral: bool = True
    bom: tuple[Edge, ...] = ()

    def __post_init__(self):
        for name in ("stock", "allocated", "incoming", "scheduled"):
            object.__setattr__(self, name, number(getattr(self, name)))


@dataclass
class Plan:
    """Aggregated target requirements and root shortages."""

    demand: dict[int, Decimal] = field(default_factory=dict)
    shortages: dict[int, Decimal] = field(default_factory=dict)
    manufacture: dict[int, Decimal] = field(default_factory=dict)

    @property
    def feasible(self):
        return not self.shortages


class Engine:
    """A plan is O(parts + BOM lines); capacity uses a bounded binary search."""

    def __init__(self, nodes: dict[int, Node], root: int):
        self.nodes = nodes
        self.root = root
        # Traverse without recursion, including the BOM of stocked assemblies:
        # malformed BOMs must not become silently valid merely because stock exists.
        reachable = set()
        pending = [root]
        while pending:
            key = pending.pop()
            if key in reachable:
                continue
            if key not in nodes:
                raise CalculationError(f"Missing part: {key}")
            reachable.add(key)
            if len(reachable) > 5000:
                raise CalculationError("BOM exceeds the 5000-part planning limit")
            pending.extend(e.child for e in nodes[key].bom)
        indegree = dict.fromkeys(reachable, 0)
        for key in reachable:
            for edge in nodes[key].bom:
                indegree[edge.child] += 1
        ready = deque(sorted(k for k, count in indegree.items() if count == 0))
        self.order = []
        while ready:
            key = ready.popleft()
            self.order.append(key)
            for edge in nodes[key].bom:
                indegree[edge.child] -= 1
                if indegree[edge.child] == 0:
                    ready.append(edge.child)
        if len(self.order) != len(reachable):
            raise CalculationError("Circular BOM detected")
        if not nodes[root].assembly or not nodes[root].bom:
            raise CalculationError("The selected part has no manufacturable BOM")

    def available(self, key: int, future=False) -> Decimal:
        node = self.nodes[key]
        return max(
            ZERO, node.stock + (node.incoming if future else ZERO) - node.scheduled
        )

    def plan(self, quantity: int, *, future=False) -> Plan:
        quantity = number(quantity)
        if quantity != int(quantity):
            raise CalculationError("Production quantity must be an integer")
        demand = defaultdict(Decimal)
        demand[self.root] = quantity
        result = Plan()
        for key in self.order:
            node = self.nodes[key]
            needed = demand[key]
            result.demand[key] = needed
            missing = (
                needed
                if key == self.root
                else max(ZERO, needed - self.available(key, future))
            )
            if not missing:
                continue
            if node.assembly and node.bom:
                batch = (
                    missing.to_integral_value(rounding=ROUND_CEILING)
                    if node.integral
                    else missing
                )
                result.manufacture[key] = batch
                for edge in node.bom:
                    demand[edge.child] += edge.required(batch)
            else:
                result.shortages[key] = missing
        return result

    def capacity(self, *, future=False) -> tuple[int, bool]:
        """Return (capacity, capped). A capped value is a lower bound."""
        low, high = 0, 1
        while high < MAX_CAPACITY and self.plan(high, future=future).feasible:
            low, high = high, min(high * 2, MAX_CAPACITY)
        if self.plan(high, future=future).feasible:
            return high, True
        while low + 1 < high:
            mid = (low + high) // 2
            if self.plan(mid, future=future).feasible:
                low = mid
            else:
                high = mid
        return low, False

    def report(self, minimum: int = 0) -> dict:
        """Return a JSON-safe explanation with decimal quantities as strings."""
        minimum_decimal = number(minimum)
        if minimum_decimal != int(minimum_decimal) or minimum_decimal > MAX_CAPACITY:
            raise CalculationError(
                "Minimum must be an integer between 0 and 1000000000"
            )
        minimum = int(minimum_decimal)
        current, capped = self.capacity()
        future, future_capped = self.capacity(future=True)
        target = self.plan(minimum)
        bottlenecks = self.plan(current + 1)

        def row(key, quantity, requirements=target):
            node = self.nodes[key]
            return {
                "part": key,
                "name": node.name,
                "ipn": node.ipn,
                "quantity": str(quantity),
                "stock": str(node.stock + node.allocated),
                "allocated": str(node.allocated),
                "available": str(self.available(key)),
                "incoming": str(node.incoming),
                "scheduled": str(node.scheduled),
                "required": str(requirements.demand.get(key, ZERO)),
            }

        # A proposal is executable only when all its downstream deficits can be
        # resolved. The entire plan shares a single material budget.
        blocked = set(target.shortages)
        for key in reversed(self.order):
            if any(edge.child in blocked for edge in self.nodes[key].bom):
                blocked.add(key)
        suggestions = [
            {**row(key, target.manufacture[key]), "materials_ready": key not in blocked}
            for key in reversed(self.order)
            if key != self.root and key in target.manufacture
        ]
        return {
            "part": self.root,
            "name": self.nodes[self.root].name,
            "ipn": self.nodes[self.root].ipn,
            "current_capacity": current,
            "future_capacity": future,
            "capacity_capped": capped,
            "future_capacity_capped": future_capped,
            "minimum": minimum,
            "shortfall": max(0, minimum - current),
            "status": "warning" if current < minimum else "ok",
            "purchase_shortages": [row(k, q) for k, q in target.shortages.items()],
            "bottlenecks": [
                row(k, q, bottlenecks) for k, q in bottlenecks.shortages.items()
            ],
            "manufacturing_suggestions": suggestions,
            "independent_product_estimate": True,
        }
