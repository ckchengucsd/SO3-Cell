# Cell geometry and solver configuration

Both files are JSON and both are passed on the command line. A missing or malformed required value
stops the generator.

    ./run_cell.sh --geometry-config /path/to/geometry.json --solver-config /path/to/solver.json ...

## Geometry

Required fields:
- schema_version
- track_count
- track_pitch_raw
- m0_power_rail_width_raw
- m0_power_rail_to_first_track_raw
- bpr_rail_width_raw
- act_bottom_anchor_raw
- legacy_act_center_anchor_raw
- sdcon.near_y_offset_raw
- sdcon.finger_length_raw
- sdcon.far_enclosure_raw
- row_scheme.pmos_near_row_by_row_scheme

For a 5-row solved log, `row_scheme.pmos_near_row_by_row_scheme` key 5 selects the physical
PMOS-near routing row for SDCON and GCUT, independently of `track_count`.

## Solver

Required fields:
- schema_version, integer 1
- solver.time_limit_seconds, positive integer, per ILP attempt
- solver.threads, non-negative integer, 0 lets the solver choose
- solver.topology_optimization, boolean
- retry.attempts, non-empty ordered array
- retry.attempts[].dummy_for_ideal_offset, integer
- retry.attempts[].dummy_padding_offset, integer
- retry.attempts[].misalign_col_offset, integer

Each retry entry adds its offsets to the command-line base values, so this file is what defines the
ordered search. A negative effective value is rejected before that attempt starts.

`solver.topology_optimization` controls the SO3-SH topology transform and defaults to `false`,
which preserves the source CDL topology. Setting it to `true` allows series-device reordering,
which can leave named inputs structurally swapped even when the Boolean function is symmetric, so
LVS against the input CDL can then fail.
