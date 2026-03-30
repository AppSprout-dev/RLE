"""Tests for helix visualizer integration with RLE agents."""

from __future__ import annotations

from felix_agent_sdk.core import HelixConfig
from felix_agent_sdk.visualization import HelixVisualizer
from rle.agents import AGENT_DISPLAY


class TestAgentDisplay:
    """Validate the AGENT_DISPLAY config constant."""

    EXPECTED_AGENTS = {
        "map_analyst", "resource_manager", "defense_commander", "research_director",
        "social_overseer", "construction_planner", "medical_officer",
    }

    def test_all_agents_present(self) -> None:
        assert set(AGENT_DISPLAY.keys()) == self.EXPECTED_AGENTS

    def test_each_has_label_and_color(self) -> None:
        for agent_id, display in AGENT_DISPLAY.items():
            assert "label" in display, f"{agent_id} missing label"
            assert "color" in display, f"{agent_id} missing color"

    def test_labels_are_two_chars(self) -> None:
        for agent_id, display in AGENT_DISPLAY.items():
            assert len(display["label"]) == 2, f"{agent_id} label is not 2 chars"

    def test_labels_are_unique(self) -> None:
        labels = [d["label"] for d in AGENT_DISPLAY.values()]
        assert len(labels) == len(set(labels))

    def test_colors_are_valid(self) -> None:
        valid = {"blue", "cyan", "yellow", "green", "red", "magenta", "white"}
        for agent_id, display in AGENT_DISPLAY.items():
            assert display["color"] in valid, f"{agent_id} has invalid color {display['color']}"


class TestVisualizerRegistration:
    """Test registering RLE agents with the HelixVisualizer."""

    def test_register_all_agents(self) -> None:
        helix = HelixConfig.default().to_geometry()
        viz = HelixVisualizer(helix, title="R L E")
        for agent_id, display in AGENT_DISPLAY.items():
            viz.register_agent(agent_id, label=display["label"], color=display["color"])
        # Update each agent — should not raise
        for agent_id in AGENT_DISPLAY:
            viz.update(agent_id, progress=0.3, confidence=0.7, phase="exploration")

    def test_render_to_string_contains_labels(self) -> None:
        helix = HelixConfig.default().to_geometry()
        viz = HelixVisualizer(helix, title="R L E")
        for agent_id, display in AGENT_DISPLAY.items():
            viz.register_agent(agent_id, label=display["label"], color=display["color"])
            viz.update(agent_id, progress=0.5, confidence=0.8, phase="analysis")
        output = viz.render_to_string(tick=100, day=5, extra_info={"score": "0.763"})
        assert len(output) > 0
        # At least some labels should appear in the sidebar
        found_labels = sum(1 for d in AGENT_DISPLAY.values() if d["label"] in output)
        assert found_labels >= 1

    def test_render_with_extra_info(self) -> None:
        helix = HelixConfig.default().to_geometry()
        viz = HelixVisualizer(helix, title="R L E")
        viz.register_agent("resource_manager", label="RM", color="green")
        viz.update("resource_manager", progress=0.1, confidence=0.6)
        output = viz.render_to_string(tick=42, day=2, extra_info={"score": "0.500"})
        assert "42" in output  # tick number should appear
        assert "0.500" in output  # extra info should appear


class TestVisualizerPhases:
    """Test that phase progression renders correctly."""

    def test_exploration_phase(self) -> None:
        helix = HelixConfig.default().to_geometry()
        viz = HelixVisualizer(helix, title="R L E")
        viz.register_agent("rm", label="RM", color="green")
        viz.update("rm", progress=0.1, confidence=0.5, phase="exploration")
        output = viz.render_to_string(tick=1)
        assert len(output) > 0

    def test_synthesis_phase(self) -> None:
        helix = HelixConfig.default().to_geometry()
        viz = HelixVisualizer(helix, title="R L E")
        viz.register_agent("rm", label="RM", color="green")
        viz.update("rm", progress=0.9, confidence=0.9, phase="synthesis")
        output = viz.render_to_string(tick=100)
        assert len(output) > 0
