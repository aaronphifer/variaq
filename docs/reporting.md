# Reporting

VariaQ 0.6 can render analysis results into reproducible reports.

## Report artifact

A report contains:

- `report_format_version`
- `report_id`
- `campaign_id` (when applicable)
- `generated_at`
- `variaq_version`
- `source_run_ids`
- full analysis result

Report IDs are deterministic from source runs and analysis query when not
explicitly supplied.

## CLI

```bash
variaq report campaign <campaign-id> --output-dir ./reports
variaq report campaign <campaign-id> --output-dir ./reports --formats json,csv
variaq report campaign <campaign-id> --output-dir ./reports --plots
```

## JSON export

JSON is the authoritative machine-readable format. It uses the same envelope
`schema_version = "1"` as other VariaQ CLI commands; the report itself has its
own `report_format_version`.

## CSV export

CSV files are generated for stable tables:

- `{report_id}_groups.csv`
- `{report_id}_scaling.csv` (when scaling points exist)

Columns are documented and stable within a report format version.

## Markdown export

Markdown is a human-readable rendering of the JSON report. It includes:

- source run ID list
- group summary table
- scaling summary
- warnings

## Plots

Plots are optional and require `matplotlib`. Generated plots include provenance
through the report artifact they are derived from. They are not the sole record
of an analysis.

## Export safety

Report commands refuse to overwrite existing files unless `--overwrite` is set.
All paths are handled via `pathlib`.
