"""Run inside InvenTree using manage.py test --keepdb (isolated test DB)."""

from decimal import Decimal
from tempfile import TemporaryDirectory

from build.models import Build, BuildItem, BuildLine
from build.status_codes import BuildStatus
from company.models import Company, SupplierPart
from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, override_settings
from django.urls import include, path
from order.models import PurchaseOrder, PurchaseOrderLineItem
from order.status_codes import PurchaseOrderStatus
from part.models import BomItem, Part
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from stock.models import StockItem

from production_capacity.core import ProductionCapacity
from production_capacity.engine import CalculationError
from production_capacity.service import calculate
from production_capacity.views import CapacityView, DashboardView

urlpatterns = [
    path("plugin/production-capacity/", include(ProductionCapacity().urlpatterns)),
    path("", include("InvenTree.urls")),
]


class CapacityModelTests(TestCase):
    """Use real ORM models including build allocation and purchase pack units."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            "capacity-admin", password="test-only"
        )
        self.root = Part.objects.create(name="Finished", assembly=True, component=True)
        self.sub = Part.objects.create(
            name="Subassembly", assembly=True, component=True
        )
        self.raw = Part.objects.create(name="Raw", component=True, purchaseable=True)
        self.line = BomItem.objects.create(
            part=self.root, sub_part=self.sub, quantity=2
        )
        self.raw_line = BomItem.objects.create(
            part=self.sub, sub_part=self.raw, quantity=3
        )
        self.stock = StockItem.objects.create(part=self.raw, quantity=30)
        self.factory = APIRequestFactory()

    def request(self, view=CapacityView, method="get", data=None, user=None, **kwargs):
        request = getattr(self.factory, method)("/capacity/", data or {}, format="json")
        force_authenticate(request, user=self.user if user is None else user)
        return view.as_view()(
            request, **({"pk": self.root.pk} if view == CapacityView else {}), **kwargs
        )

    def test_real_recursive_bom_and_subassembly_inventory(self):
        assert calculate(self.root)["current_capacity"] == 5
        StockItem.objects.create(part=self.sub, quantity=4)
        assert calculate(self.root)["current_capacity"] == 7

    def test_shared_raw_at_multiple_levels(self):
        BomItem.objects.create(part=self.root, sub_part=self.raw, quantity=4)
        assert calculate(self.root)["current_capacity"] == 3

    def test_allocated_and_unallocated_build_demand_no_double_subtraction(self):
        build = Build.objects.create(
            part=self.sub,
            quantity=4,
            reference="BO-9001",
            status=BuildStatus.PRODUCTION.value,
        )
        line, _ = BuildLine.objects.update_or_create(
            build=build,
            bom_item=self.raw_line,
            defaults={"quantity": 12, "consumed": 0},
        )
        BuildItem.objects.create(build_line=line, stock_item=self.stock, quantity=5)
        result = calculate(self.root)
        assert result["current_capacity"] == 3  # 30 - 5 allocated - 7 scheduled = 18

    def test_consumed_stock_and_building_output_are_excluded(self):
        build = Build.objects.create(part=self.sub, quantity=2, reference="BO-9002")
        StockItem.objects.create(part=self.raw, quantity=100, consumed_by=build)
        StockItem.objects.create(
            part=self.sub, quantity=100, is_building=True, build=build
        )
        BuildLine.objects.filter(
            build=build
        ).delete()  # this case only tests stock filters
        assert calculate(self.root)["current_capacity"] == 5

    def test_partial_purchase_receipt_pack_units_and_draft_exclusion(self):
        supplier = Company.objects.create(name="Supplier", is_supplier=True)
        item = SupplierPart.objects.create(
            part=self.raw, supplier=supplier, SKU="PACK", pack_quantity="5"
        )
        order = PurchaseOrder.objects.create(
            supplier=supplier,
            reference="CAP-PO-01",
            status=PurchaseOrderStatus.PLACED.value,
        )
        PurchaseOrderLineItem.objects.create(
            order=order, part=item, quantity=4, received=1
        )
        draft = PurchaseOrder.objects.create(
            supplier=supplier,
            reference="CAP-PO-02",
            status=PurchaseOrderStatus.PENDING.value,
        )
        PurchaseOrderLineItem.objects.create(order=draft, part=item, quantity=100)
        result = calculate(self.root)
        assert result["current_capacity"] == 5
        assert result["future_capacity"] == 7  # 30 + (4 - 1) * 5 = 45

    def test_bom_required_quantity_matches_official_implementation(self):
        self.raw_line.quantity = Decimal("0.1")
        self.raw_line.piece_count = 3
        self.raw_line.attrition = Decimal("10")
        self.raw_line.setup_quantity = Decimal("0.5")
        self.raw_line.rounding_multiple = Decimal("0.25")
        self.raw_line.save()
        from production_capacity.service import snapshot

        engine, _ = snapshot(self.root)
        edge = engine.nodes[self.sub.pk].bom[0]
        for batch in [1, 5, 11, 100]:
            assert edge.required(Decimal(batch)) == self.raw_line.get_required_quantity(
                batch
            )

    def test_cycle_in_corrupt_database_is_rejected(self):
        # bulk_create bypasses InvenTree's application-level circular-BOM guard.
        BomItem.objects.bulk_create(
            [BomItem(part=self.sub, sub_part=self.root, quantity=1)]
        )
        with self.assertRaisesRegex(CalculationError, "Circular"):
            calculate(self.root)

    def test_metadata_patch_preserves_other_namespaces_and_warns(self):
        self.root.set_metadata("other-plugin", {"keep": True})
        response = self.request(method="patch", data={"minimum": 8})
        assert response.status_code == 200
        self.root.refresh_from_db()
        assert self.root.get_metadata("other-plugin") == {"keep": True}
        result = self.request().data
        assert result["minimum"] == 8 and result["shortfall"] == 3
        assert result["status"] == "warning" and result["can_edit_minimum"]
        assert Decimal(result["purchase_shortages"][0]["quantity"]) == 18

    def test_invalid_api_targets_and_pagination(self):
        for value in [-1, True, 1.5, "10", None, 1000000001]:
            assert (
                self.request(method="patch", data={"minimum": value}).status_code == 400
            )
        request = self.factory.get("/capacity/?limit=0")
        force_authenticate(request, user=self.user)
        assert DashboardView.as_view()(request).status_code == 400

    def test_anonymous_and_unprivileged_access_denied(self):
        assert self.request(user=AnonymousUser()).status_code in (401, 403)
        user = User.objects.create_user("capacity-no-permissions")
        assert self.request(user=user).status_code == 403
        assert (
            self.request(method="patch", data={"minimum": 5}, user=user).status_code
            == 403
        )

    def test_dashboard_opt_in_and_data_change_reflected(self):
        assert self.request(DashboardView).data["count"] == 0
        self.request(method="patch", data={"minimum": 6})
        rows = self.request(DashboardView).data["results"]
        assert rows[0]["status"] == "warning"
        self.stock.quantity = 60
        self.stock.save()
        assert self.request(DashboardView).data["results"][0]["current_capacity"] == 10

    def test_entrypoint_and_official_ui_features(self):
        from importlib.metadata import entry_points

        entry = next(
            e
            for e in entry_points(group="inventree_plugins")
            if e.name == "ProductionCapacity"
        )
        assert entry.load() is ProductionCapacity
        from django.contrib.staticfiles.storage import staticfiles_storage
        from plugin.models import PluginConfig
        from plugin.registry import registry
        from plugin.staticfiles import copy_plugin_static_files

        registry.reload_plugins(force_reload=True, collect=True)
        plugin = registry.get_plugin("production-capacity", active=None)
        assert plugin is not None
        PluginConfig.objects.filter(key="production-capacity").update(active=True)
        with (
            TemporaryDirectory() as directory,
            override_settings(STATIC_ROOT=directory),
        ):
            copy_plugin_static_files("production-capacity", check_reload=False)
            assert staticfiles_storage.exists("plugins/production-capacity/Capacity.js")
            assert len(plugin.urlpatterns) == 2
            assert (
                plugin.get_ui_panels(None, {"target_model": "part"})[0]["key"]
                == "production-capacity"
            )
            assert not plugin.get_ui_panels(None, {"target_model": "stockitem"})
            assert plugin.get_ui_dashboard_items(None, {})[0]["source"].endswith(
                "Capacity.js:renderDashboardItem"
            )

    @override_settings(ROOT_URLCONF="tests.integration.test_models")
    def test_http_route_and_session_csrf_protection(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = f"/plugin/production-capacity/capacity/{self.root.pk}/"
        assert client.get(url).status_code == 200
        assert client.patch(url, {"minimum": 10}, format="json").status_code == 403

    def test_read_only_permissions_cannot_change_target(self):
        from django.contrib.auth.models import Permission

        user = User.objects.create_user("capacity-reader")
        for app, model in [
            ("part", "part"),
            ("part", "bomitem"),
            ("stock", "stockitem"),
            ("build", "build"),
            ("order", "purchaseorder"),
            ("order", "salesorder"),
            ("order", "transferorder"),
        ]:
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app, codename=f"view_{model}"
                )
            )
        response = self.request(user=user)
        assert response.status_code == 200 and not response.data["can_edit_minimum"]
        assert (
            self.request(method="patch", data={"minimum": 10}, user=user).status_code
            == 403
        )

    def test_external_stock_and_optional_consumable_bom_excluded(self):
        from stock.models import StockLocation

        external = StockLocation.objects.create(name="External", external=True)
        StockItem.objects.create(part=self.raw, quantity=100, location=external)
        optional = Part.objects.create(name="Optional", component=True)
        BomItem.objects.create(
            part=self.root, sub_part=optional, quantity=10, optional=True
        )
        consumable = Part.objects.create(
            name="Consumable", component=True, consumable=True
        )
        BomItem.objects.create(part=self.root, sub_part=consumable, quantity=10)
        result = calculate(self.root)
        assert result["current_capacity"] == 5
        assert result["warnings"]

    def test_invalid_metadata_produces_calculation_error(self):
        Part.objects.filter(pk=self.root.pk).update(metadata=["corrupt"])
        assert self.request().status_code == 400
        assert self.request(method="patch", data={"minimum": 5}).status_code == 400

    def test_inherited_bom_uses_exact_stock_without_variant_double_counting(self):
        self.sub.is_template = True
        self.sub.save()
        self.raw.is_template = True
        self.raw.save()
        self.raw_line.inherited = True
        self.raw_line.save()
        variant = Part.objects.create(
            name="Variant assembly", variant_of=self.sub, assembly=True, component=True
        )
        variant_raw = Part.objects.create(
            name="Variant raw", variant_of=self.raw, component=True
        )
        StockItem.objects.create(part=variant_raw, quantity=100)
        report = calculate(variant)
        assert report["current_capacity"] == 10
        assert [
            (row["part"], row["capacity"]) for row in report["material_limits"]
        ] == [(self.raw.pk, 10)]
