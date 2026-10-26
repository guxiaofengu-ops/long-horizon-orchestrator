# Security policy

## Supported versions

Security fixes are applied to the latest release and the `main` branch.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting for this repository. Do not include live credentials, sensitive logs, or customer data. If private reporting is unavailable, open a minimal issue asking the maintainer to enable a private channel without disclosing the vulnerability.

## Operational boundary

This tool executes commands with the invoking user's permissions. Review every task contract before starting it. Prefer argv arrays over shell strings, use a dedicated workspace, set finite budgets, and use least-privilege scheduler/service accounts. Wakeup thread IDs are routing metadata, not authorization tokens.
