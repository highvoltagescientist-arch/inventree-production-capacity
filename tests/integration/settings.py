"""Keep the plugin test database separate from both live and core test data."""

from InvenTree.settings import *  # noqa: F403
from InvenTree.settings import DATABASES

DATABASES["default"]["TEST"] = {"NAME": "test_production_capacity"}
PLUGIN_TESTING_SETUP = True
