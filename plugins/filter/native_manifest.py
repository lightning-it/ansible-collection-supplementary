"""Private, type-aware comparison of complete native Pod manifests."""

import json

import yaml
from ansible.errors import AnsibleFilterError


class UniqueMappingLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate keys instead of silently keeping the last."""


def unique_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("ambiguous manifest mapping")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueMappingLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def native_manifest_equal(original, desired):
    """Ignore presentation only; preserve scalar types and sequence ordering."""
    try:
        normalized = []
        for content in (original, desired):
            if not isinstance(content, str) or not content or len(content) > 1_048_576:
                raise ValueError("invalid manifest input")
            # SafeLoader subclass additionally rejects ambiguous mapping keys.
            loader = UniqueMappingLoader(content)
            try:
                document = loader.get_single_data()
            finally:
                loader.dispose()
            if not isinstance(document, dict) or document.get("kind") != "Pod":
                raise ValueError("complete Pod manifest required")
            normalized.append(json.dumps(document, sort_keys=True, allow_nan=False, separators=(",", ":")))
        return normalized[0] == normalized[1]
    except (ValueError, TypeError, RecursionError, yaml.YAMLError):
        raise AnsibleFilterError("Native manifest comparison rejected") from None


class FilterModule:
    def filters(self):
        return {"native_manifest_equal": native_manifest_equal}
