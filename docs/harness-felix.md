# Felix harness options

The Felix multi-agent stack is an in-tree harness behind the optional `felix`
extra. **RLE does not modify `felix-agent-sdk`.** Roster selection, per-role
timeouts, and action merge policy are harness-layer only.

```bash
python scripts/run_scenario.py crashlanded --harness felix
python scripts/run_scenario.py crashlanded --harness felix \
  --harness-opt roles=map_analyst,resource_manager,medical_officer \
  --harness-opt role_timeout_s=180
python scripts/run_scenario.py crashlanded --harness felix \
  --harness-opt exclude_agent=construction_planner,social_overseer
```

## Options (`FelixOptions`)

| Opt | Default | Meaning |
|-----|---------|---------|
| `parallel` | `true` | Role agents deliberate concurrently (MapAnalyst always first). |
| `no_think` | `false` | Inject a `</think>` prefill for thinking models. |
| `helix_preset` | `default` | `default` \| `research_heavy` \| `fast_convergence`. |
| `role_timeout_s` | `60` | Per-agent wall clock. On timeout the harness emits a structured `ERROR` (`deliberation_timeout`) and that agent contributes **no** actions — the resolver never sees a partial plan. Raise this for slow models; do not special-case a role with canned blueprints. |
| `roles` | unset (= all 7) | Include list (comma-separated or JSON). Canonical order is preserved. |
| `exclude_agent` | unset | Drop one or more role ids (single id, comma-separated, or JSON list). Applied after `roles`. |
| `provider_kwargs` | `{}` | Extra kwargs for `provider.complete()`. |
| `visualize` | `false` | Terminal helix visualiser. |

Default roster is unchanged: MapAnalyst + six roles. Ablation is `--harness-opt roles=...` and/or `--harness-opt exclude_agent=...`. An empty roster is rejected (use `--harness baseline`).

## Action merge

`ActionResolver` (used by Felix after deliberation) arbitrates conflicting
writes generally:

- Group pawn-targeted writes by `(colonist_id, canonical action_type)` so
  `work_priority` and `time_assignment` on the same pawn **both** apply.
- Same-type conflicts: lower `Action.priority`, then the role-priority table
  (defense promoted during a raid, medical during a medical emergency), then
  higher plan confidence, then **last-writer**.
- `work_priority` merges per work type (Growing from ResourceManager +
  Construction from ConstructionPlanner; conflicting values for the same
  work type pick a winner).
- `no_action` never vetoes another role's real write.
- Timed-out deliberations are omitted before `resolve()`.
