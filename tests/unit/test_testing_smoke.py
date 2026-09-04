"""rle.testing.run_harness_smoke — the contract test external plugins run in CI."""

from __future__ import annotations

import pytest

from rle.testing import MockRimAPI, run_harness_smoke
from tests.conftest import requires_felix


@pytest.mark.parametrize(
    "name", ["baseline", pytest.param("felix", marks=requires_felix)],
)
async def test_builtin_plugins_pass_smoke(name: str) -> None:
    report = await run_harness_smoke(name, ticks=2)
    assert report.ok
    assert report.harness == name
    assert len(report.ticks) == 2
    assert report.final_composite is not None
    assert report.describe["harness"] == name


async def test_smoke_records_posts() -> None:
    mock = MockRimAPI()
    report = await run_harness_smoke("baseline", ticks=1, mock=mock)
    # pause + unpause at minimum went through the mock
    assert any(path.startswith("/api/v1/game/speed") for path, _ in report.posts)


async def test_smoke_validates_options() -> None:
    from rle.harness import HarnessOptionsError

    with pytest.raises(HarnessOptionsError):
        await run_harness_smoke("baseline", options={"nope": 1})
