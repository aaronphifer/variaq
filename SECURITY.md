# Security policy

## Reporting

Please use GitHub private vulnerability reporting once enabled. Until then, do
not publish credentials, exploitable details, or sensitive reproduction data in
a public issue. This document should be updated with the repository's private
reporting channel once one exists; no security email is currently designated.

Ordinary non-sensitive defects may use a normal bug report.

## Current model

VariaQ 0.2 executes and stores experiments locally. Normal tests require no
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
`--allow-qpu`. This functionality does not exist in VariaQ 0.2.
