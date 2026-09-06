"""FelixOptions parsing and roster selection (no Felix SDK)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rle.harness.felix.options import (
    CANONICAL_ROLES,
    FelixOptions,
    select_role_ids,
)
from rle.harness.registry import get_plugin, parse_option_pairs, validate_options


class TestFelixOptionsParsing:
    def test_default_is_full_roster(self) -> None:
        opts = FelixOptions()
        assert opts.roles is None
        assert opts.exclude_agent is None
        assert opts.role_timeout_s == 60.0
        assert select_role_ids(roles=opts.roles, exclude_agent=opts.exclude_agent) == list(
            CANONICAL_ROLES,
        )

    def test_comma_separated_roles(self) -> None:
        opts = FelixOptions.model_validate({"roles": "map_analyst,resource_manager"})
        assert opts.roles == ["map_analyst", "resource_manager"]
        assert select_role_ids(roles=opts.roles) == ["map_analyst", "resource_manager"]

    def test_json_list_roles_via_cli_pairs(self) -> None:
        raw = parse_option_pairs(['roles=["map_analyst","medical_officer"]'])
        opts = FelixOptions.model_validate(raw)
        assert opts.roles == ["map_analyst", "medical_officer"]

    def test_multi_exclude_comma_and_list(self) -> None:
        comma = FelixOptions.model_validate({
            "exclude_agent": "construction_planner,social_overseer",
        })
        listed = FelixOptions.model_validate({
            "exclude_agent": ["construction_planner", "social_overseer"],
        })
        assert comma.exclude_agent == listed.exclude_agent == [
            "construction_planner", "social_overseer",
        ]
        selected = select_role_ids(exclude_agent=comma.exclude_agent)
        assert "construction_planner" not in selected
        assert "social_overseer" not in selected
        assert "map_analyst" in selected
        assert len(selected) == 5

    def test_roles_plus_exclude(self) -> None:
        selected = select_role_ids(
            roles=["map_analyst", "resource_manager", "medical_officer"],
            exclude_agent=["medical_officer"],
        )
        assert selected == ["map_analyst", "resource_manager"]

    def test_unknown_role_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown Felix role"):
            FelixOptions.model_validate({"roles": "not_a_role"})

    def test_empty_roster_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            select_role_ids(roles=["map_analyst"], exclude_agent=["map_analyst"])

    def test_single_exclude_string_still_works(self) -> None:
        """Ablation scripts pass exclude_agent as one id."""
        opts = FelixOptions.model_validate({"exclude_agent": "construction_planner"})
        assert opts.exclude_agent == ["construction_planner"]

    def test_plugin_schema_accepts_roles(self) -> None:
        plugin = get_plugin("felix")
        opts = validate_options(plugin, {"roles": "map_analyst", "role_timeout_s": 180})
        assert isinstance(opts, FelixOptions)
        assert opts.roles == ["map_analyst"]
        assert opts.role_timeout_s == 180.0
