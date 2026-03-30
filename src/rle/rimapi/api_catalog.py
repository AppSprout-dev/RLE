"""Full RIMAPI endpoint catalog extracted from C# controller source.

Generated from upstream RIMAPI develop (2026-03-30).
166 endpoints across 24 controllers.

Agents use the WRITE catalog to propose actions and the READ catalog
to understand colony state. The game loop uses GAME_CONTROL for
pause/unpause/save/load.
"""

from __future__ import annotations

# -- GAME CONTROL (used by game loop, not agents) --------------------------

GAME_CONTROL = {
    "pause": {"method": "POST", "path": "/api/v1/game/speed", "params": {"speed": 0}},
    "unpause": {"method": "POST", "path": "/api/v1/game/speed", "params": {"speed": 3}},
    "save": {"method": "POST", "path": "/api/v1/game/save"},
    "load": {"method": "POST", "path": "/api/v1/game/load"},
    "game_state": {"method": "GET", "path": "/api/v1/game/state"},
}

# -- READ ENDPOINTS (pre-fetched into GameState or available on demand) -----

READ_CATALOG = {
    # Colonists
    "colonists": {
        "method": "GET",
        "path": "/api/v1/colonists",
        "description": "Basic list of all colonists (id, name, health, mood, hunger, position)",
    },
    "colonists_detailed": {
        "method": "GET",
        "path": "/api/v1/colonists/detailed",
        "description": "Full colonist data: skills, traits, jobs, priorities, needs, medical",
    },
    "colonist_detailed": {
        "method": "GET",
        "path": "/api/v1/colonist/detailed",
        "description": "Single colonist full data",
        "params": ["id"],
    },
    "colonist_inventory": {
        "method": "GET",
        "path": "/api/v1/colonist/inventory",
        "description": "Colonist equipment and carried items",
        "params": ["id"],
    },
    "colonist_opinion": {
        "method": "GET",
        "path": "/api/v1/colonist/opinion-about",
        "description": "Social opinion between two colonists",
        "params": ["id", "target_id"],
    },
    "colonists_positions": {
        "method": "GET",
        "path": "/api/v1/colonists/positions",
        "description": "All colonist positions on map",
    },
    # Map
    "map_zones": {
        "method": "GET",
        "path": "/api/v1/map/zones",
        "description": "All zones (growing, stockpile, dumping) with cell counts and labels",
        "params": ["map_id"],
    },
    "map_rooms": {
        "method": "GET",
        "path": "/api/v1/map/rooms",
        "description": "All rooms with role (bedroom, kitchen), temperature, size, bed IDs",
        "params": ["map_id"],
    },
    "map_buildings": {
        "method": "GET",
        "path": "/api/v1/map/buildings",
        "description": "All buildings/structures on the map",
        "params": ["map_id"],
    },
    "map_building_info": {
        "method": "GET",
        "path": "/api/v1/map/building/info",
        "description": "Detailed info about a specific building",
        "params": ["map_id", "building_id"],
    },
    "map_power": {
        "method": "GET",
        "path": "/api/v1/map/power/info",
        "description": "Power grid: generation, consumption, batteries, connected buildings",
        "params": ["map_id"],
    },
    "map_weather": {
        "method": "GET",
        "path": "/api/v1/map/weather",
        "description": "Current weather condition and temperature",
        "params": ["map_id"],
    },
    "map_farm_summary": {
        "method": "GET",
        "path": "/api/v1/map/farm/summary",
        "description": "Farm production stats: growing zones, planted crops, harvest estimates",
        "params": ["map_id"],
    },
    "map_terrain": {
        "method": "GET",
        "path": "/api/v1/map/terrain",
        "description": "Full terrain grid with palette",
        "params": ["map_id"],
    },
    "map_things": {
        "method": "GET",
        "path": "/api/v1/map/things",
        "description": "All things (items, corpses, etc.) on the map",
        "params": ["map_id"],
    },
    "map_things_at": {
        "method": "GET",
        "path": "/api/v1/map/things-at",
        "description": "Things at a specific position",
        "params": ["map_id", "x", "z"],
    },
    "map_things_radius": {
        "method": "GET",
        "path": "/api/v1/map/things/radius",
        "description": "Things within a radius of a position",
        "params": ["map_id", "x", "z", "radius"],
    },
    "map_animals": {
        "method": "GET",
        "path": "/api/v1/map/animals",
        "description": "All animals on the map",
        "params": ["map_id"],
    },
    "map_plants": {
        "method": "GET",
        "path": "/api/v1/map/plants",
        "description": "All plants on the map",
        "params": ["map_id"],
    },
    "map_creatures_summary": {
        "method": "GET",
        "path": "/api/v1/map/creatures/summary",
        "description": "Summary of all creatures (colonists, animals, enemies)",
        "params": ["map_id"],
    },
    "map_growing_zone": {
        "method": "GET",
        "path": "/api/v1/map/zone/growing",
        "description": "Details of a specific growing zone",
        "params": ["map_id", "zone_id"],
    },
    "map_ore": {
        "method": "GET",
        "path": "/api/v1/map/ore",
        "description": "Ore deposits on the map",
        "params": ["map_id"],
    },
    "maps": {
        "method": "GET",
        "path": "/api/v1/maps",
        "description": "List of all maps",
    },
    # Resources
    "resources_summary": {
        "method": "GET",
        "path": "/api/v1/resources/summary",
        "description": "Resource totals: food, medicine, weapons, market value",
        "params": ["map_id"],
    },
    "resources_stored": {
        "method": "GET",
        "path": "/api/v1/resources/stored",
        "description": "All stored items by category",
        "params": ["map_id"],
    },
    "resources_storages": {
        "method": "GET",
        "path": "/api/v1/resources/storages/summary",
        "description": "Storage zone summaries with capacity",
        "params": ["map_id"],
    },
    # Research
    "research_summary": {
        "method": "GET",
        "path": "/api/v1/research/summary",
        "description": "Research progress: finished count, available count, by tech level",
    },
    "research_tree": {
        "method": "GET",
        "path": "/api/v1/research/tree",
        "description": "Full tech tree with prerequisites, costs, descriptions",
    },
    "research_progress": {
        "method": "GET",
        "path": "/api/v1/research/progress",
        "description": "Current research project progress",
    },
    "research_finished": {
        "method": "GET",
        "path": "/api/v1/research/finished",
        "description": "List of completed research projects",
    },
    "research_project": {
        "method": "GET",
        "path": "/api/v1/research/project",
        "description": "Details of a specific research project",
        "params": ["name"],
    },
    # Factions
    "factions": {
        "method": "GET",
        "path": "/api/v1/factions",
        "description": "All factions with goodwill and relation status",
    },
    "faction_relations": {
        "method": "GET",
        "path": "/api/v1/faction/relations",
        "description": "Detailed faction relations",
    },
    # Incidents / Threats
    "incidents": {
        "method": "GET",
        "path": "/api/v1/incidents",
        "description": "Active incidents and events",
        "params": ["map_id"],
    },
    "incidents_top": {
        "method": "GET",
        "path": "/api/v1/incidents/top",
        "description": "Most likely upcoming incidents",
        "params": ["map_id"],
    },
    "incident_chance": {
        "method": "GET",
        "path": "/api/v1/incident/chance",
        "description": "Probability of a specific incident type",
        "params": ["map_id", "incident_def"],
    },
    # World
    "world_settlements": {
        "method": "GET",
        "path": "/api/v1/world/settlements",
        "description": "All world map settlements",
    },
    "world_caravans": {
        "method": "GET",
        "path": "/api/v1/world/caravans",
        "description": "Active caravans",
    },
    "world_sites": {
        "method": "GET",
        "path": "/api/v1/world/sites",
        "description": "World map sites (quests, ruins, etc.)",
    },
    # Definitions
    "def_all": {
        "method": "GET",
        "path": "/api/v1/def/all",
        "description": "All game definitions (things, buildings, plants, jobs, work types)",
    },
    "work_list": {
        "method": "GET",
        "path": "/api/v1/work-list",
        "description": "Available work types for colonist assignment",
    },
    "time_assignments": {
        "method": "GET",
        "path": "/api/v1/time-assignments",
        "description": "Current time assignment schedules",
    },
    "outfits": {
        "method": "GET",
        "path": "/api/v1/outfits",
        "description": "Outfit policies",
    },
    "quests": {
        "method": "GET",
        "path": "/api/v1/quests",
        "description": "Active quests",
    },
    "traders": {
        "method": "GET",
        "path": "/api/v1/traders/defs",
        "description": "Available trader types",
    },
}

# -- WRITE ENDPOINTS (agents propose these as actions) ----------------------

WRITE_CATALOG = {
    # Pawn management
    "work_priority": {
        "method": "POST",
        "path": "/api/v1/colonist/work-priority",
        "description": "Set a colonist's priority for a work type (1=highest, 4=lowest)",
        "params": {
            "id": "int (colonist ID)",
            "work": "string (e.g. Growing, Mining)",
            "priority": "int (1-4)",
        },
    },
    "draft": {
        "method": "POST",
        "path": "/api/v1/pawn/edit/status",
        "description": "Draft or undraft a colonist for combat",
        "params": {"pawn_id": "int", "is_drafted": "bool"},
    },
    "move": {
        "method": "POST",
        "path": "/api/v1/pawn/edit/position",
        "description": "Move a colonist to a position",
        "params": {"pawn_id": "int", "position": {"x": "int", "y": 0, "z": "int"}},
    },
    "job_assign": {
        "method": "POST",
        "path": "/api/v1/pawn/job",
        "description": "Assign a specific job to a colonist",
        "params": {
            "pawn_id": "int",
            "job_def": "string",
            "target_thing_id": "int? (optional)",
            "target_position": "position? (optional)",
        },
    },
    "time_assignment": {
        "method": "POST",
        "path": "/api/v1/colonist/time-assignment",
        "description": "Set schedule for a colonist at a specific hour",
        "params": {
            "pawn_id": "int",
            "hour": "int (0-23)",
            "assignment": "string (Work, Sleep, Joy, Anything)",
        },
    },
    "equip": {
        "method": "POST",
        "path": "/api/v1/jobs/make/equip",
        "description": "Make a colonist equip an item",
        "params": {"pawn_id": "int", "thing_id": "int"},
    },
    # Medical
    "bed_rest": {
        "method": "POST",
        "path": "/api/v1/pawn/medical/bed-rest",
        "description": "Assign a colonist to bed rest",
        "params": {"patient_pawn_id": "int", "bed_building_id": "int? (optional)"},
    },
    "tend": {
        "method": "POST",
        "path": "/api/v1/pawn/medical/tend",
        "description": "Have a doctor tend to a patient",
        "params": {"patient_pawn_id": "int", "doctor_pawn_id": "int? (optional)"},
    },
    # Construction / Zones
    "blueprint": {
        "method": "POST",
        "path": "/api/v1/builder/blueprint",
        "description": "Place building blueprints using a grid (walls, doors, beds, etc.)",
        "params": {
            "map_id": "int",
            "position": {"x": "int", "y": 0, "z": "int"},
            "blueprint": {
                "width": "int",
                "height": "int",
                "buildings": [
                    {
                        "def_name": "string",
                        "stuff_def_name": "string",
                        "rel_x": "int",
                        "rel_z": "int",
                        "rotation": "int (0-3)",
                    }
                ],
            },
            "clear_obstacles": "bool (default true)",
        },
    },
    "growing_zone": {
        "method": "POST",
        "path": "/api/v1/map/zone/growing",
        "description": "Create a growing zone for food production",
        "params": {
            "map_id": "int",
            "plant_def": "string (e.g. Plant_Potato)",
            "point_a": "position",
            "point_b": "position",
        },
    },
    "stockpile_zone": {
        "method": "POST",
        "path": "/api/v1/map/zone/stockpile",
        "description": "Create a stockpile zone for item storage",
        "params": {
            "map_id": "int",
            "point_a": "position",
            "point_b": "position",
            "name": "string? (optional)",
            "priority": "int? (1=Critical, 2=High, 3=Normal, 4=Low)",
            "allowed_item_defs": "list[string]? (optional)",
            "allowed_item_categories": "list[string]? (optional)",
        },
    },
    "stockpile_update": {
        "method": "POST",
        "path": "/api/v1/map/zone/stockpile/update",
        "description": "Update an existing stockpile zone",
    },
    "stockpile_delete": {
        "method": "DELETE",
        "path": "/api/v1/map/zone/stockpile/delete",
        "description": "Delete a stockpile zone",
        "params": {"zone_id": "int"},
    },
    "designate_area": {
        "method": "POST",
        "path": "/api/v1/order/designate/area",
        "description": "Designate an area for mining, harvesting, deconstructing, or hunting",
        "params": {
            "map_id": "int",
            "type": "string (Mine, Harvest, Deconstruct, Hunt)",
            "point_a": "position",
            "point_b": "position",
        },
    },
    "toggle_power": {
        "method": "POST",
        "path": "/api/v1/map/building/power",
        "description": "Toggle power on/off for a building",
        "params": {"buildingId": "int", "powerOn": "bool"},
    },
    "destroy_rect": {
        "method": "POST",
        "path": "/api/v1/map/destroy/rect",
        "description": "Destroy all things in a rectangular area",
        "params": {"map_id": "int", "point_a": "position", "point_b": "position"},
    },
    "repair_rect": {
        "method": "POST",
        "path": "/api/v1/map/repair/rect",
        "description": "Repair all damaged buildings in a rectangular area",
        "params": {"map_id": "int", "point_a": "position", "point_b": "position"},
    },
    # Research
    "research_target": {
        "method": "POST",
        "path": "/api/v1/research/target",
        "description": "Set the current research target",
        "params": {"name": "string (defName)", "force": "bool? (bypass prerequisites)"},
    },
    "research_stop": {
        "method": "POST",
        "path": "/api/v1/research/stop",
        "description": "Stop current research",
    },
    # Weather
    "change_weather": {
        "method": "POST",
        "path": "/api/v1/map/weather/change",
        "description": "Change the current weather",
        "params": {"map_id": "int", "weather_def": "string"},
    },
    # Items
    "spawn_item": {
        "method": "POST",
        "path": "/api/v1/item/spawn",
        "description": "Spawn an item on the map",
        "params": {"map_id": "int", "def_name": "string", "position": "position", "count": "int?"},
    },
    # Incidents (dev/testing)
    "trigger_incident": {
        "method": "POST",
        "path": "/api/v1/incident/trigger",
        "description": "Trigger a game incident (raid, toxic fallout, etc.)",
        "params": {"map_id": "int", "incident_def": "string"},
    },
    # Pawn spawning (dev/testing)
    "spawn_pawn": {
        "method": "POST",
        "path": "/api/v1/pawn/spawn",
        "description": "Spawn a new pawn on the map",
    },
    # Drop pod
    "drop_pod": {
        "method": "POST",
        "path": "/api/v1/map/droppod",
        "description": "Send a drop pod with items",
    },
}

# -- AGENT-RELEVANT subsets -------------------------------------------------

RESOURCE_ENDPOINTS = {
    "work_priority",
    "growing_zone",
    "stockpile_zone",
    "designate_area",
    "toggle_power",
    "job_assign",
}

DEFENSE_ENDPOINTS = {
    "draft",
    "move",
    "job_assign",
}

RESEARCH_ENDPOINTS = {
    "research_target",
    "research_stop",
    "work_priority",
}

SOCIAL_ENDPOINTS = {
    "time_assignment",
    "work_priority",
}

CONSTRUCTION_ENDPOINTS = {
    "blueprint",
    "designate_area",
    "repair_rect",
    "destroy_rect",
}

MEDICAL_ENDPOINTS = {
    "bed_rest",
    "tend",
    "work_priority",
}

# All write endpoints agents are allowed to use (excludes dev/testing)
AGENT_WRITE_ENDPOINTS = (
    RESOURCE_ENDPOINTS
    | DEFENSE_ENDPOINTS
    | RESEARCH_ENDPOINTS
    | SOCIAL_ENDPOINTS
    | CONSTRUCTION_ENDPOINTS
    | MEDICAL_ENDPOINTS
)
