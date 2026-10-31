"""Authenticated, permission-checked REST endpoints."""

from build.models import Build
from django.db import transaction
from django.shortcuts import get_object_or_404
from order.models import PurchaseOrder, SalesOrder, TransferOrder
from part.models import BomItem, Part
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from stock.models import StockItem
from users.permissions import check_user_permission

from .engine import MAX_CAPACITY, CalculationError
from .service import METADATA_KEY, calculate


def can_edit(user):
    return check_user_permission(user, Part, "change")


class CapacityPermission(BasePermission):
    """Respect the same model access rules as InvenTree's native APIs."""

    def has_permission(self, request, view):
        return all(
            check_user_permission(request.user, model, "view")
            for model in (
                Part,
                BomItem,
                StockItem,
                Build,
                PurchaseOrder,
                SalesOrder,
                TransferOrder,
            )
        )


class CapacityView(APIView):
    permission_classes = [IsAuthenticated, CapacityPermission]

    def get(self, request, pk):
        part = get_object_or_404(Part, pk=pk)
        try:
            result = calculate(part)
        except CalculationError as exc:
            raise ValidationError({"calculation": str(exc)}) from exc
        result["can_edit_minimum"] = can_edit(request.user)
        return Response(result)

    def patch(self, request, pk):
        if not can_edit(request.user):
            raise PermissionDenied("Part change permission required")
        minimum = request.data.get("minimum")
        if type(minimum) is not int or not 0 <= minimum <= MAX_CAPACITY:
            raise ValidationError(
                {"minimum": "0～1000000000の整数を指定してください。"}
            )
        with transaction.atomic():
            part = get_object_or_404(Part.objects.select_for_update(), pk=pk)
            if part.metadata is not None and not isinstance(part.metadata, dict):
                raise ValidationError({"minimum": "部品メタデータが不正です。"})
            data = part.get_metadata(METADATA_KEY, {})
            if not isinstance(data, dict):
                raise ValidationError({"minimum": "保存済みメタデータが不正です。"})
            part.set_metadata(METADATA_KEY, {**data, "minimum": minimum}, commit=False)
            part.save(update_fields=["metadata"])
        return Response({"part": pk, "minimum": minimum})


class DashboardView(APIView):
    permission_classes = [IsAuthenticated, CapacityPermission]

    def get(self, request):
        try:
            offset = int(request.query_params.get("offset", "0"))
            limit = int(request.query_params.get("limit", "25"))
        except (ValueError, TypeError) as exc:
            raise ValidationError("Invalid pagination") from exc
        if offset < 0 or not 1 <= limit <= 100:
            raise ValidationError("offset >= 0, 1 <= limit <= 100")
        # Only explicitly monitored products: opt in by saving a minimum.
        parts = Part.objects.filter(
            active=True,
            assembly=True,
            metadata__production_capacity__minimum__isnull=False,
        ).order_by("pk")
        count = parts.count()
        rows = []
        for part in parts[offset : offset + limit]:
            try:
                rows.append(calculate(part))
            except CalculationError as exc:
                rows.append(
                    {
                        "part": part.pk,
                        "name": part.name,
                        "ipn": part.IPN,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        rows.sort(
            key=lambda row: (
                row["status"] == "ok",
                -row.get("shortfall", 0),
                row["part"],
            )
        )
        return Response(
            {"count": count, "offset": offset, "limit": limit, "results": rows}
        )
