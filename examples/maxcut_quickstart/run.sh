#!/usr/bin/env bash
set -euo pipefail

output_dir="${1:-data/examples/maxcut_quickstart}"
problem_path="${output_dir}/problem.json"
database_path="${output_dir}/runs.sqlite3"

mkdir -p "${output_dir}"

variaq --db "${database_path}" problem generate maxcut \
  --nodes 8 --edge-probability 0.4 --seed 42 \
  --output "${problem_path}"

variaq --db "${database_path}" benchmark "${problem_path}" \
  --solvers exact,heuristic,qaoa --seed 42

variaq --db "${database_path}" runs list
