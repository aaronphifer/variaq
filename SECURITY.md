# Security policy

## Reporting

Please use GitHub private vulnerability reporting once enabled. Until then, do
not publish credentials, exploitable details, or sensitive reproduction data in
a public issue. This document should be updated with the repository's private
reporting channel once one exists; no security email is currently designated.

Ordinary non-sensitive defects may use a normal bug report.

## Current model

VariaQ executes and stores experiments locally. Normal tests require no
credentials and no network. Never commit API keys, IBM credentials, cloud
tokens, private keys, or user experiment databases.

No physical-QPU or IBM Runtime/provider integration exists. Only local
simulator targets are supported.

## Future remote execution

Future remote or QPU support must require unmistakable explicit authorization,
keep secrets outside the repository, identify the provider/backend, distinguish
queue/execution/charge timing, remain disabled in normal tests, and never be an
implicit fallback.

A future interface may require both `--backend ibm:<backend>` and
`--allow-qpu`. This functionality does not exist in VariaQ.

## Local web boundary (v0.8 candidate)

The default listener binds to `127.0.0.1`. Default local mode validates Host
headers and refuses cross-origin/browser cross-site writes. It has no authentication
and is not an internet service. Explicit non-loopback mode retains the trusted-lab
boundary, prints a warning, and permits arbitrary hostnames; it is not hardened for
DNS rebinding, hostile LAN clients or public exposure. Local applications can invoke
the JSON API without browser Origin headers.

Requests validate bounded generator dimensions and solver budgets, in addition to
the existing run-count and solver state/memory guards. They provide no shell, raw SQL
or arbitrary filesystem selector. Imported problems are JSON data with canonical
family validation, not executable adapters. SQLite, problem/report directories and
the adjacent worker lock are trusted local files; do not share writable access with
untrusted users. Do not rename/delete the worker lock while the server is alive.
Report exporters refuse output symlinks, and downloads enforce known artifact names
and root containment. These checks do not defend against a hostile local process
racing filesystem operations. Native GPU calls have no safe in-process timeout or
cancellation. Stop the process if it hangs, inspect preserved records, and explicitly
plan subsequent work; no automatic retry is performed.
