#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
# GNU General Public License v3.0+ alternative: https://www.gnu.org/licenses/gpl-3.0.txt
# ruff: noqa: E402, UP017
"""Read the latest encrypted backup across every S3 list page."""

DOCUMENTATION = r"""
---
module: hetzner_s3_backup_freshness
short_description: Enforce a maximum age for an encrypted S3 database backup
description:
  - Paginates the complete dedicated service prefix instead of trusting one S3 page.
  - Uses S3 LastModified rather than a timestamp embedded in an object name.
  - Reports the latest 20 objects and optionally enforces a maximum age.
requirements:
  - boto3
  - botocore
options:
  bucket:
    description: Dedicated backup bucket.
    type: str
    required: true
  endpoint_url:
    description: HTTPS S3 endpoint.
    type: str
    required: true
  region:
    description: S3 region.
    type: str
    required: true
  access_key:
    description: Read-only bucket access key.
    type: str
    required: true
  secret_key:
    description: Read-only bucket secret key.
    type: str
    required: true
  prefix:
    description: Exact service directory prefix, ending in a slash.
    type: str
    required: true
  service:
    description: Database service name used in backup object names.
    type: str
    required: true
    choices: [keycloak, netbox, guacamole]
  max_age_seconds:
    description: Optional maximum acceptable age measured from S3 LastModified.
    type: int
  validate_certs:
    description: Verify the S3 endpoint certificate.
    type: bool
    default: true
author:
  - Lightning IT (@litroc)
"""

EXAMPLES = r"""
- name: Require a recent Keycloak backup
  lit.supplementary.hetzner_s3_backup_freshness:
    bucket: example-backup
    endpoint_url: https://nbg1.your-objectstorage.com
    region: nbg1
    access_key: "{{ backup_reader_access_key }}"
    secret_key: "{{ backup_reader_secret_key }}"
    prefix: management-services/keycloak/
    service: keycloak
    max_age_seconds: 3600
  no_log: true
"""

RETURN = r"""
latest_object:
  description: Latest matching backup object key.
  type: str
  returned: success
age_seconds:
  description: Age of the latest object based on S3 LastModified.
  type: int
  returned: success
matching_objects:
  description: Number of nonempty matching backup objects across all pages.
  type: int
  returned: success
recent_objects:
  description: Up to 20 most recent matching object keys.
  type: list
  elements: str
  returned: success
"""

import datetime
import heapq
import re
from urllib.parse import urlsplit

from ansible.module_utils.basic import AnsibleModule

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None


def latest_backup(pages, prefix, service, now, max_pages=1000):
    """Select one real S3 object timestamp, with a finite pagination bound."""
    pattern = re.compile(
        r"\A" + re.escape(prefix) + r"postgres-" + re.escape(service) + r"-\d{8}T\d{6}Z\.dump\.vault\Z"
    )
    latest = None
    count = 0
    recent = []
    for page_number, page in enumerate(pages, start=1):
        if page_number > max_pages:
            raise ValueError("S3 backup listing exceeded its page limit")
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            modified = item.get("LastModified")
            if not pattern.fullmatch(key) or item.get("Size", 0) <= 0:
                continue
            if not isinstance(modified, datetime.datetime) or modified.tzinfo is None:
                raise ValueError("S3 backup object lacks a timezone-aware LastModified")
            if modified > now + datetime.timedelta(minutes=5):
                raise ValueError("S3 backup object has a future LastModified")
            count += 1
            if len(recent) < 20:
                heapq.heappush(recent, (modified, key))
            elif (modified, key) > recent[0]:
                heapq.heapreplace(recent, (modified, key))
            if latest is None or (modified, key) > (latest[1], latest[0]):
                latest = (key, modified)
    if latest is None:
        raise ValueError("No nonempty encrypted backup object exists")
    age = max(0, int((now - latest[1]).total_seconds()))
    return {
        "latest_object": latest[0],
        "age_seconds": age,
        "matching_objects": count,
        "recent_objects": [key for _modified, key in sorted(recent, reverse=True)],
    }


def require_fresh(result, max_age_seconds):
    if max_age_seconds is not None and result["age_seconds"] > max_age_seconds:
        raise ValueError("Encrypted backup is older than the declared RPO")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bucket=dict(type="str", required=True),
            endpoint_url=dict(type="str", required=True),
            region=dict(type="str", required=True),
            access_key=dict(type="str", required=True, no_log=True),
            secret_key=dict(type="str", required=True, no_log=True),
            prefix=dict(type="str", required=True),
            service=dict(type="str", required=True, choices=["keycloak", "netbox", "guacamole"]),
            max_age_seconds=dict(type="int", default=None),
            validate_certs=dict(type="bool", default=True),
        ),
        supports_check_mode=True,
    )
    args = module.params
    if boto3 is None:
        module.fail_json(msg="boto3 and botocore are required in the controller runtime")
    endpoint = urlsplit(args["endpoint_url"])
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path
        or endpoint.query
        or endpoint.fragment
        or not args["validate_certs"]
        or not args["prefix"].endswith("/")
        or args["prefix"].startswith("/")
        or ".." in args["prefix"].split("/")
        or (
            args["max_age_seconds"] is not None
            and (args["max_age_seconds"] < 1 or args["max_age_seconds"] > 31 * 86400)
        )
    ):
        module.fail_json(msg="Unsafe backup freshness contract")
    try:
        client = boto3.client(
            "s3",
            endpoint_url=args["endpoint_url"],
            region_name=args["region"],
            aws_access_key_id=args["access_key"],
            aws_secret_access_key=args["secret_key"],
            verify=True,
            config=Config(signature_version="s3v4"),
        )
        pages = client.get_paginator("list_objects_v2").paginate(
            Bucket=args["bucket"],
            Prefix=args["prefix"],
            PaginationConfig={"PageSize": 1000},
        )
        result = latest_backup(
            pages,
            args["prefix"],
            args["service"],
            datetime.datetime.now(datetime.timezone.utc),
        )
        require_fresh(result, args["max_age_seconds"])
    except ValueError as error:
        module.fail_json(msg=str(error))
    except (BotoCoreError, ClientError):
        module.fail_json(msg="S3 backup freshness request failed")
    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
