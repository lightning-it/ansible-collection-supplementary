#!/usr/bin/env python3
"""Compatibility entry point for the collection-wide evidence framework."""

from quality_evidence import main

if __name__ == "__main__":
    raise SystemExit(
        main(
            default_roles=("keycloak",),
            mandatory_scenarios=(
                "keycloak-tiny",
                "keycloak-heavy",
                "keycloak-application-acceptance",
            ),
            default_release=True,
        )
    )
