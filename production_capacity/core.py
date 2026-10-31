"""Plugin Creator scaffold adapted for capacity planning (no AppMixin needed)."""

from plugin import InvenTreePlugin
from plugin.mixins import UrlsMixin, UserInterfaceMixin

from . import __version__


class ProductionCapacity(UrlsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "ProductionCapacity"
    SLUG = "production-capacity"
    TITLE = "製造余力管理"
    DESCRIPTION = "多階層BOMと引当を考慮した製造可能数量"
    VERSION = __version__
    MIN_VERSION = "1.6.3"

    def setup_urls(self):
        from django.urls import path

        from .views import CapacityView, DashboardView

        return [
            path("capacity/", DashboardView.as_view(), name="capacity-list"),
            path("capacity/<int:pk>/", CapacityView.as_view(), name="capacity-detail"),
        ]

    def get_ui_panels(self, request, context, **kwargs):
        if (context or {}).get("target_model") != "part":
            return []
        return [
            {
                "key": "production-capacity",
                "title": "製造余力",
                "icon": "ti:building-factory-2:outline",
                "source": self.plugin_static_file("Capacity.js:renderPanel"),
            }
        ]

    def get_ui_dashboard_items(self, request, context, **kwargs):
        return [
            {
                "key": "production-capacity",
                "title": "製造余力一覧",
                "description": "監視対象製品の製造余力と不足数量",
                "source": self.plugin_static_file("Capacity.js:renderDashboardItem"),
                "options": {"width": 2, "height": 1},
            }
        ]

    def get_ui_routes(self, request, context, **kwargs):
        return [
            {
                "key": "production-capacity-list",
                "title": "製造余力一覧",
                "source": self.plugin_static_file("Capacity.js:renderCapacityListPage"),
                "options": {"path": "capacity"},
            }
        ]
