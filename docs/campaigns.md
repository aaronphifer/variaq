# Campaigns

VariaQ 0.6 introduces **experiment campaigns**: controlled, reproducible sets of
runs that answer "what happened across this controlled set of experiments?"

A campaign is a serializable definition. Running it generates normal VariaQ run
records and records campaign membership in the same SQLite database.

## Campaign definition

Campaign files are JSON. Example:

```json
{
  "campaign_format_version": "1",
  "name": "maxcut-scaling-p1",
  "family": "maxcut",
  "problem_sizes": [4, 6, 8],
  "problem_seeds": [1, 2],
  "solvers": ["exact", "heuristic", "qaoa"],
  "repeats": 2,
  "base_seed": 0,
  "solver_config": {
    "qaoa": {
      "seed": 42,
      "parameters": {
        "p": 1,
        "optimizer_trials": 32,
        "shots": 1024
      }
    }
  },
  "generator_parameters": {
    "edge_probability": 0.4
  },
  "tags": ["scaling"]
}
```

Fields:

- `name`, `family` — required.
- `problem_sizes` — list of integer logical sizes.
- `problem_seeds` — list of problem-generation seeds.
- `solvers` — list of solver names.
- `repeats` — solver repeats per problem instance (default 1).
- `base_seed` — default solver seed.
- `solver_config` — optional per-solver overrides.
- `generator_parameters` — family-specific generator parameters.

## Planning a campaign

```bash
variaq campaign plan examples/campaigns/maxcut_scaling.json --json
```

`plan` does not execute solvers. It reports requested run counts, solver
availability, estimated quantum runs, max binary variables, and warnings about
the default run limit.

## Running a campaign

```bash
variaq campaign run examples/campaigns/maxcut_scaling.json --json
```

Campaigns are bounded by a default maximum run count. Override with
`--override-max-runs` or `--max-runs N`.

## Listing and showing campaigns

```bash
variaq campaign list
variaq campaign show campaign-<id>
```

## Failure isolation

A single failed run does not stop the campaign. The runner records successes,
failures, unavailable backends, and skipped solvers in the campaign summary.

## Repeats

A repeat varies solver seed/sampling randomness while keeping the same problem
and configuration. Problem seeds are independent of repeat seeds.

## Limitations

- Campaign generator support is built in for the four core families.
- Very large campaigns should use `--max-runs` and `--override-max-runs`
  deliberately.
