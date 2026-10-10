#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# SPDX-License-Identifier: MIT
# ruff: noqa: E402
"""Reconcile the one abort rule on a dedicated Hetzner backup bucket."""

DOCUMENTATION = r"""
---
module: hetzner_s3_abort_lifecycle
short_description: Reconcile multipart cleanup on a dedicated Hetzner bucket
description:
  - Owns the complete lifecycle configuration of one dedicated backup bucket.
  - Accepts provider-normalized C(Prefix) in place of C(Filter) for an empty prefix.
  - Refuses to replace unrelated lifecycle rules.
requirements:
  - boto3
  - botocore
options:
  bucket:
    description: Dedicated bucket name.
    type: str
    required: true
  endpoint_url:
    description: Hetzner regional S3 endpoint.
    type: str
    required: true
  region:
    description: Hetzner Object Storage region.
    type: str
    required: true
  access_key:
    description: Bucket administrative access key.
    type: str
    required: true
    no_log: true
  secret_key:
    description: Bucket administrative secret key.
    type: str
    required: true
    no_log: true
  abort_days:
    description: Days before incomplete multipart uploads are aborted.
    type: int
    required: true
  validate_certs:
    description: Verify the S3 endpoint certificate.
    type: bool
    default: true
author:
  - Lightning IT
"""

EXAMPLES = r"""
- name: Reconcile incomplete uploads on a dedicated backup bucket
  lit.supplementary.hetzner_s3_abort_lifecycle:
    bucket: example-backup
    endpoint_url: https://nbg1.your-objectstorage.com
    region: nbg1
    access_key: "{{ bucket_admin_access_key }}"
    secret_key: "{{ bucket_admin_secret_key }}"
    abort_days: 7
  no_log: true
"""

RETURN = r"""
rules_before:
  description: Number of existing lifecycle rules.
  type: int
  returned: always
rules_after:
  description: Number of lifecycle rules after reconciliation.
  type: int
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None


RULE_ID = "abort-incomplete-multipart-uploads"
ALLOWED_RULE_KEYS = frozenset(
    {"ID", "Status", "Filter", "Prefix", "AbortIncompleteMultipartUpload"}
)


def is_owned_rule(rule, days):
    """Accept only the exact cleanup action, including Hetzner's Prefix form."""
    if not isinstance(rule, dict) or set(rule) - ALLOWED_RULE_KEYS:
        return False
    if rule.get("Status") != "Enabled" or rule.get("Prefix", "") != "":
        return False
    if rule.get("Filter", {"Prefix": ""}) not in ({"Prefix": ""}, {}):
        return False
    return rule.get("AbortIncompleteMultipartUpload") == {"DaysAfterInitiation": days}


def s3_error_code(error):
    return str(error.response.get("Error", {}).get("Code", "unknown"))


def read_rules(client, bucket, module):
    try:
        return client.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except ClientError as error:
        if s3_error_code(error) == "NoSuchLifecycleConfiguration":
            return []
        module.fail_json(msg="Cannot read bucket lifecycle", error_code=s3_error_code(error))


def main():
    module = AnsibleModule(
        argument_spec={
            "bucket": {"type": "str", "required": True},
            "endpoint_url": {"type": "str", "required": True},
            "region": {"type": "str", "required": True},
            "access_key": {"type": "str", "required": True, "no_log": True},
            "secret_key": {"type": "str", "required": True, "no_log": True},
            "abort_days": {"type": "int", "required": True},
            "validate_certs": {"type": "bool", "default": True},
        },
        supports_check_mode=True,
    )
    p = module.params
    if boto3 is None:
        module.fail_json(msg="boto3 and botocore are required in the controller runtime")
    if p["abort_days"] < 1 or not p["endpoint_url"].startswith("https://"):
        module.fail_json(msg="Require a positive abort period and HTTPS endpoint")

    client = boto3.client(
        "s3",
        endpoint_url=p["endpoint_url"],
        region_name=p["region"],
        aws_access_key_id=p["access_key"],
        aws_secret_access_key=p["secret_key"],
        verify=p["validate_certs"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
    )
    rules = read_rules(client, p["bucket"], module)
    if any(not is_owned_rule(rule, p["abort_days"]) for rule in rules):
        module.fail_json(msg="An unrelated lifecycle rule exists; refusing to replace it")
    if len(rules) == 1:
        module.exit_json(changed=False, rules_before=1, rules_after=1)
    if module.check_mode:
        module.exit_json(changed=True, rules_before=len(rules), rules_after=1)

    desired = {
        "ID": RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": p["abort_days"]},
    }
    try:
        client.put_bucket_lifecycle_configuration(
            Bucket=p["bucket"], LifecycleConfiguration={"Rules": [desired]}
        )
    except ClientError as error:
        module.fail_json(msg="Cannot reconcile bucket lifecycle", error_code=s3_error_code(error))
    verified = read_rules(client, p["bucket"], module)
    if len(verified) != 1 or not is_owned_rule(verified[0], p["abort_days"]):
        module.fail_json(msg="Bucket lifecycle readback did not match the declared rule")
    module.exit_json(changed=True, rules_before=len(rules), rules_after=1)


if __name__ == "__main__":
    main()
