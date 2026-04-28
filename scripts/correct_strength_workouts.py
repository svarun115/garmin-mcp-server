"""Reconcile Garmin exerciseSets with the user's phone-typed description for
known activities, then PUT the corrected payload back.

Usage:
    uv run python scripts/correct_strength_workouts.py [--dry-run] <activity_id>

The mappings below were built by hand against the user's description text.
Each row replaces a single ACTIVE set (REST sets are passed through unchanged).
Set count and timing are preserved; only category, repetitionCount, and weight
change. Weight in kg (converted to grams for Garmin).
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin


# Per-activity mapping: list of (category, reps, weight_kg) or
# (category, reps, weight_kg, name) for each ACTIVE set, in the order they
# appear in Garmin's exerciseSets. Length must match the number of ACTIVE sets.
# `name` is the specific exercise sub-name from FIT SDK's <category>_exercise_name
# enum (e.g. 'lat_pulldown' under PULL_UP, 'barbell_high_pull' under OLYMPIC_LIFT).
# Setting name controls how the Garmin UI labels the exercise.
MAPPINGS = {
    # 3/30 — 23 active sets. Description:
    #   Indoor Bike: 10 mins
    #   Cable Single arm lat pull down: 2 x 15 x 12.5 kg
    #   Cable Single arm lateral raise: 2 x 15 x 7.5 kg
    #   Cable Single Leg Curls: 3 x 12 x 7 kg
    #   Jefferson Curls: 4 x 12 x 13.5 kg
    #   Bar High Pulls: 1 x 12 x 42.5 kg, 3 x 12 x 52kg
    #   Bar Deadlifts: 4 x 10 x 74.5 kg
    #   Alternating DB Bicep Curls: 30, 24, 20, 16, 12  (at 9 kg)
    22350211111: [
        ("WARM_UP",       0,   0.0),   # 1 (pre-bike setup, ~4.6 min)
        ("CARDIO",        0,   0.0),   # 2 (Indoor Bike 10 min)
        ("PULL_UP",      30,  12.5),   # 3 (Cable lat pulldown — API can't set sub-name; UI shows "Weighted Pull Up")
        ("LATERAL_RAISE",15,   7.5),   # 4 (Lateral raise R1)
        ("LATERAL_RAISE",15,   7.5),   # 5 (Lateral raise R2)
        ("LEG_CURL",     36,   7.0),   # 6 (Cable single leg curl 3x12)
        ("HYPEREXTENSION",12,  13.5),  # 7 Jefferson curl R1 (closest cat — spinal flexion/posterior chain)
        ("HYPEREXTENSION",12,  13.5),  # 8 Jefferson curl R2
        ("HYPEREXTENSION",12,  13.5),  # 9 Jefferson curl R3
        ("HYPEREXTENSION",12,  13.5),  # 10 Jefferson curl R4
        ("OLYMPIC_LIFT", 12,  42.5),   # 11 High pull warmup
        ("OLYMPIC_LIFT", 12,  52.0),   # 12 High pull working 1
        ("OLYMPIC_LIFT", 12,  52.0),   # 13 High pull working 2
        ("OLYMPIC_LIFT", 12,  52.0),   # 14 High pull working 3
        ("DEADLIFT",     10,  74.5),                              # 15 Deadlift 1
        ("DEADLIFT",     10,  74.5),                              # 16 Deadlift 2
        ("DEADLIFT",     10,  74.5),                              # 17 Deadlift 3
        ("DEADLIFT",     10,  74.5),                              # 18 Deadlift 4
        ("CURL",         30,   9.0),                              # 19 Alt DB Curl ladder 1
        ("CURL",         24,   9.0),                              # 20 ladder 2
        ("CURL",         20,   9.0),                              # 21 ladder 3
        ("CURL",         16,   9.0),                              # 22 ladder 4
        ("CURL",         12,   9.0),                              # 23 ladder 5
    ],

    # 4/21 — 32 active sets. Description:
    #   WU for 3:30
    #   Alternating Kettlebell Swing and Squats:
    #     R1,R2: 24 KB @ 13.5kg, 24 BW squats
    #     R3,R4: 24 KB @ 13.5kg, 16 weighted squats @ 13.5kg
    #   Shoulder Isometrics (Rotator Cuff + Lat isolation): 8 mins
    #   Romanian Deadlift: 4 rounds, 27.5kg each hand, 12 reps
    #     (Garmin recorded 5 sets here — keep all 5 as RDL with same params)
    #   Cable Face Pulls: 4 rounds, 52kg, 12 reps
    #   Lat pull downs: 4 rounds, 49kg, 12 reps
    #   Barbell Bicep Curls: 4 rounds, 16 reps, 16.5kg
    #   Windmills: 4 rounds, 12 reps each side (24 total), 16.5kg
    #   Superman tabata: 8 min (Garmin split into 2 long sets)
    22613115758: [
        ("WARM_UP",       0,   0.0),   # 1 WU 3:23
        ("ROW",          24,  13.5),   # 2 KB swing R1 (closest cat)
        ("SQUAT",        24,   0.0),   # 3 BW squat R1
        ("ROW",          24,  13.5),   # 4 KB swing R2
        ("SQUAT",        24,   0.0),   # 5 BW squat R2
        ("ROW",          24,  13.5),   # 6 KB swing R3
        ("SQUAT",        16,  13.5),   # 7 Weighted squat R3
        ("ROW",          24,  13.5),   # 8 KB swing R4
        ("SQUAT",        16,  13.5),   # 9 Weighted squat R4
        ("WARM_UP",      16,   0.0),   # 10 Shoulder Isometrics 8 min (closest cat: WARM_UP for static hold)
        ("DEADLIFT",     12,  27.5),   # 11 RDL 1
        ("DEADLIFT",     12,  27.5),   # 12 RDL 2
        ("DEADLIFT",     12,  27.5),   # 13 RDL 3
        ("DEADLIFT",     12,  27.5),   # 14 RDL 4
        ("DEADLIFT",     12,  27.5),   # 15 RDL 5 (Garmin had extra; keep)
        ("ROW",          12,  52.0),   # 16 Face pull 1
        ("ROW",          12,  52.0),   # 17 Face pull 2
        ("ROW",          12,  52.0),   # 18 Face pull 3
        ("ROW",          12,  52.0),   # 19 Face pull 4
        ("PULL_UP",      12,  49.0),   # 20 Lat pulldown 1
        ("PULL_UP",      12,  49.0),   # 21 Lat pulldown 2
        ("PULL_UP",      12,  49.0),   # 22 Lat pulldown 3
        ("PULL_UP",      12,  49.0),   # 23 Lat pulldown 4
        ("CURL",         16,  16.5),   # 24 BB Bicep curl 1
        ("CURL",         16,  16.5),   # 25 BB Bicep curl 2
        ("CURL",         16,  16.5),   # 26 BB Bicep curl 3
        ("CURL",         16,  16.5),   # 27 BB Bicep curl 4
        ("CURL",         24,  16.5),   # 28 Windmill 1 (closest cat)
        ("CURL",         24,  16.5),   # 29 Windmill 2
        ("CURL",         24,  16.5),   # 30 Windmill 3
        ("CURL",         24,  16.5),   # 31 Windmill 4
        ("CRUNCH",        0,   0.0),   # 32 Superman tabata block 1
        ("CRUNCH",        0,   0.0),   # (would be 33 if it existed; only 32 present)
    ][:32],

    # 3/25 — 26 active sets. Journal narrative:
    #   Jump Rope warmup (8:45) + working (11:22)
    #   Arnold Press (4) ↔ Goblet Squat (4)  alternating, 15 reps × 13.6kg
    #   Plate Halos (4) ↔ Cossack Squats (4) alternating, 24 reps; halos w/ 11.3kg, cossacks BW
    #   Plank (4) ↔ Butterfly Sit-ups (4) descending: 120/90/60/30s plank, 20/15/10/5 reps situp
    22295433898: [
        ("WARM_UP",         0,    0.0),                              # 1 Jump rope warmup
        ("CARDIO",        296,    0.0, "JUMP_ROPE"),                 # 2 Jump rope working
        ("SHOULDER_PRESS", 15,   13.5),                              # 3 Arnold Press 1
        ("SQUAT",          15,   13.5),                              # 4 Goblet Squat 1
        ("SHOULDER_PRESS", 15,   13.5),                              # 5 Arnold Press 2
        ("SQUAT",          15,   13.5),                              # 6 Goblet Squat 2
        ("SHOULDER_PRESS", 15,   13.5),                              # 7 Arnold Press 3
        ("SQUAT",          15,   13.5),                              # 8 Goblet Squat 3
        ("SHOULDER_PRESS", 15,   13.5),                              # 9 Arnold Press 4
        ("SQUAT",          15,   13.5),                              # 10 Goblet Squat 4
        ("SHOULDER_STABILITY", 24, 11.3),                            # 11 Plate Halo 1
        ("SQUAT",          24,    0.0),                              # 12 Cossack Squat 1
        ("SHOULDER_STABILITY", 24, 11.3),                            # 13 Plate Halo 2
        ("SQUAT",          24,    0.0),                              # 14 Cossack Squat 2
        ("SHOULDER_STABILITY", 24, 11.3),                            # 15 Plate Halo 3
        ("SQUAT",          24,    0.0),                              # 16 Cossack Squat 3
        ("SHOULDER_STABILITY", 24, 11.3),                            # 17 Plate Halo 4
        ("SQUAT",          24,    0.0),                              # 18 Cossack Squat 4
        ("PLANK",           0,    0.0),                              # 19 Plank 1 (~120s)
        ("SIT_UP",         20,    0.0),                              # 20 Butterfly Sit-up 1
        ("PLANK",           0,    0.0),                              # 21 Plank 2 (~90s)
        ("SIT_UP",         15,    0.0),                              # 22 Butterfly Sit-up 2
        ("PLANK",           0,    0.0),                              # 23 Plank 3 (~60s)
        ("SIT_UP",         10,    0.0),                              # 24 Butterfly Sit-up 3
        ("PLANK",           0,    0.0),                              # 25 Plank 4 (~30s)
        ("SIT_UP",          5,    0.0),                              # 26 Butterfly Sit-up 4
    ],

    # 4/14 — 27 active sets. Journal narrative:
    #   (warmup not captured in journal — keep set 1 as WARM_UP)
    #   Bodyweight Dips: 5 × 10 reps
    #   Leg Extension single-leg: 4 × 12 × 21kg
    #   Inclined DB Press: 12@9, 12@18.5, 10@22.5, 8@22.5, 5@22.5
    #   Knee Up Drive: 3 × 12 × 8kg
    #   Cable Flies: 12@6 warmup, 12@8 × 3
    #   DB Tricep Extension: 10, 8, 8 reps × 12kg
    #   Hollow Hold + Leg Tuck-ins (Tabata, 1 long set each)
    22523721130: [
        ("WARM_UP",          0,   0.0),                                       # 1 Warmup ~5min
        ("TRICEPS_EXTENSION", 10, 0.0, "BODY_WEIGHT_DIP"),                    # 2 Dip 1 (cat per 4/23 user-edit)
        ("TRICEPS_EXTENSION", 10, 0.0, "BODY_WEIGHT_DIP"),                    # 3 Dip 2
        ("TRICEPS_EXTENSION", 10, 0.0, "BODY_WEIGHT_DIP"),                    # 4 Dip 3
        ("TRICEPS_EXTENSION", 10, 0.0, "BODY_WEIGHT_DIP"),                    # 5 Dip 4
        ("TRICEPS_EXTENSION", 10, 0.0, "BODY_WEIGHT_DIP"),                    # 6 Dip 5
        ("CRUNCH",          12,  21.0, "WEIGHTED_LEG_EXTENSIONS"),            # 7 Leg Ext 1 (cat per 3/20 user-edit)
        ("CRUNCH",          12,  21.0, "WEIGHTED_LEG_EXTENSIONS"),            # 8 Leg Ext 2
        ("CRUNCH",          12,  21.0, "WEIGHTED_LEG_EXTENSIONS"),            # 9 Leg Ext 3
        ("CRUNCH",          12,  21.0, "WEIGHTED_LEG_EXTENSIONS"),            # 10 Leg Ext 4
        ("BENCH_PRESS",     12,   9.0, "INCLINE_DUMBBELL_BENCH_PRESS"),       # 11 Incline DB Press warmup
        ("BENCH_PRESS",     12,  18.5, "INCLINE_DUMBBELL_BENCH_PRESS"),       # 12 Incline DB Press 2
        ("BENCH_PRESS",     10,  22.5, "INCLINE_DUMBBELL_BENCH_PRESS"),       # 13 Incline DB Press 3
        ("BENCH_PRESS",      8,  22.5, "INCLINE_DUMBBELL_BENCH_PRESS"),       # 14 Incline DB Press 4
        ("BENCH_PRESS",      5,  22.5, "INCLINE_DUMBBELL_BENCH_PRESS"),       # 15 Incline DB Press 5
        ("HIP_RAISE",       12,   8.0),                                       # 16 Knee Up Drive 1 (closest cat for hip flexor)
        ("HIP_RAISE",       12,   8.0),                                       # 17 Knee Up Drive 2
        ("HIP_RAISE",       12,   8.0),                                       # 18 Knee Up Drive 3
        ("FLYE",            12,   6.0),                                       # 19 Cable Flye warmup
        ("FLYE",            12,   8.0),                                       # 20 Cable Flye 1
        ("FLYE",            12,   8.0),                                       # 21 Cable Flye 2
        ("FLYE",            12,   8.0),                                       # 22 Cable Flye 3
        ("TRICEPS_EXTENSION", 10, 12.0),                                      # 23 Tricep Ext 1
        ("TRICEPS_EXTENSION",  8, 12.0),                                      # 24 Tricep Ext 2
        ("TRICEPS_EXTENSION",  8, 12.0),                                      # 25 Tricep Ext 3
        ("PLANK",            0,   0.0),                                       # 26 Hollow Hold tabata block (kept long duration)
        ("SIT_UP",           0,   0.0),                                       # 27 Leg Tuck-ins tabata block
    ],
}


def build_corrected_payload(original: dict, mapping: list[tuple[str, int, float]]) -> dict:
    """Return a deep-copied payload with ACTIVE sets rewritten from the mapping."""
    new = deepcopy(original)
    sets = new["exerciseSets"]
    active_indices = [i for i, s in enumerate(sets) if s.get("setType") == "ACTIVE"]
    if len(active_indices) != len(mapping):
        raise ValueError(
            f"set count mismatch: garmin has {len(active_indices)} ACTIVE sets, "
            f"mapping has {len(mapping)}"
        )
    for set_idx, row in zip(active_indices, mapping):
        category, reps, weight_kg = row[0], row[1], row[2]
        name = row[3] if len(row) >= 4 else None
        s = sets[set_idx]
        s["exercises"] = [{"category": category, "name": name, "probability": 100.0}]
        s["repetitionCount"] = reps
        s["weight"] = float(weight_kg) * 1000.0  # kg -> grams
    return new


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if not a.startswith("--")]
    if len(args) != 1:
        print("usage: correct_strength_workouts.py [--dry-run] <activity_id>")
        return 2
    activity_id = int(args[0])

    if activity_id not in MAPPINGS:
        print(f"no mapping defined for activity {activity_id}")
        return 2

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    g = Garmin()
    g.login(str(Path.home() / ".garminconnect"))

    print(f"--- fetch current exerciseSets for {activity_id} ---")
    original = g.get_activity_exercise_sets(activity_id)
    n_active = sum(1 for s in original["exerciseSets"] if s.get("setType") == "ACTIVE")
    print(f"  active sets: {n_active}, mapping rows: {len(MAPPINGS[activity_id])}")

    print(f"\n--- build corrected payload ---")
    corrected = build_corrected_payload(original, MAPPINGS[activity_id])
    diff_path = Path(f"/tmp/garmin_{activity_id}.corrected.json")
    diff_path.write_text(json.dumps(corrected, indent=2))
    print(f"  wrote corrected payload to {diff_path}")

    if dry_run:
        print("\n--- DRY RUN: not PUTting ---")
        print("\nproposed mapping:")
        for i, row in enumerate(MAPPINGS[activity_id], 1):
            cat, reps, w = row[0], row[1], row[2]
            name = row[3] if len(row) >= 4 else None
            name_str = f" name={name}" if name else ""
            print(f"  {i:2d}. {cat:22s}  reps={reps:3d}  weight={w}kg{name_str}")
        return 0

    print(f"\n--- PUT corrected payload ---")
    url = f"/activity-service/activity/{activity_id}/exerciseSets"
    resp = g.garth.put("connectapi", url, json=corrected, api=True)
    print(f"  status: {resp.status_code}")
    print("✅ correction PUT complete." if resp.status_code in (200, 204) else "⚠️  unexpected status")

    return 0 if resp.status_code in (200, 204) else 1


if __name__ == "__main__":
    sys.exit(main())
