"""Pagination and timestamp boundaries for encrypted S3 backup freshness."""

# ruff: noqa: UP017

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hetzner_s3_backup_freshness",
    ROOT / "plugins/modules/hetzner_s3_backup_freshness.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BackupFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)
        self.prefix = "management-services/keycloak/"

    def item(self, suffix, minutes_ago, size=1024):
        return {"Key": self.prefix + suffix,
                "LastModified": self.now - timedelta(minutes=minutes_ago),
                "Size": size}

    def test_latest_object_on_second_page_uses_s3_time(self):
        pages = [
            {"Contents": [self.item("postgres-keycloak-20261008T021000Z.dump.vault", 50)]},
            {"Contents": [self.item("postgres-keycloak-20261008T025500Z.dump.vault", 5)]},
        ]
        result = MODULE.latest_backup(iter(pages), self.prefix, "keycloak", self.now)
        self.assertEqual(result["age_seconds"], 300)
        self.assertEqual(result["matching_objects"], 2)
        self.assertTrue(result["latest_object"].endswith("025500Z.dump.vault"))
        self.assertEqual(result["recent_objects"], [
            self.prefix + "postgres-keycloak-20261008T025500Z.dump.vault",
            self.prefix + "postgres-keycloak-20261008T021000Z.dump.vault",
        ])

    def test_empty_and_unrelated_objects_cannot_claim_freshness(self):
        pages = [{"Contents": [
            self.item("postgres-keycloak-20261008T025900Z.dump.vault", 1, size=0),
            self.item("postgres-guacamole-20261008T025900Z.dump.vault", 1),
        ]}]
        with self.assertRaisesRegex(ValueError, "No nonempty"):
            MODULE.latest_backup(iter(pages), self.prefix, "keycloak", self.now)

    def test_future_s3_time_fails_closed(self):
        pages = [{"Contents": [self.item(
            "postgres-keycloak-20261008T030000Z.dump.vault", -6)]}]
        with self.assertRaisesRegex(ValueError, "future LastModified"):
            MODULE.latest_backup(iter(pages), self.prefix, "keycloak", self.now)

    def test_listing_page_limit_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "page limit"):
            MODULE.latest_backup(({} for _ in range(1001)),
                                 self.prefix, "keycloak", self.now)

    def test_declared_rpo_rejects_a_stale_object(self):
        result = {"age_seconds": 3601}
        with self.assertRaisesRegex(ValueError, "older than the declared RPO"):
            MODULE.require_fresh(result, 3600)
        MODULE.require_fresh(result, None)


if __name__ == "__main__":
    unittest.main()
