# Spec: evidence-contract

## Objective

Make the repository's Markdown trustworthy without rewriting history. Current
runbooks describe only supported and measured behavior; historical notes carry
their date, target versions, and supersession status; hypotheses are labeled.

## Tech Stack

Markdown, Git history, PowerShell/Python validation scripts already available in
the repository environment.

## Commands

- Inventory: `rg --files --hidden -g '*.md' -g '!\.git/**' -g '!\.pytest_cache/**'`
- Link scan: `rg -n 'https?://' README.md CLAUDE.md docs android-relay/README.md`
- Server tests: `py -3.12 -m pytest -q`
- Lint: `ruff check .`

## Project Structure

- `README.md`, `CLAUDE.md`: current entrypoint and engineering contract.
- `docs/`: current runbooks, historical findings, research, and decisions.
- `android-relay/README.md`: Android relay contract.
- `.agents/progress/`: internal historical continuation records, not runbooks.

## Code Style

```markdown
Status: Historical measurement; superseded for current operation.
Measured tuple: firmware X / service Y / relay Z / commit SHA.
```

Use precise version tuples and source links. Do not convert observations into
platform-wide guarantees.

## Testing Strategy

Automated searches check stale version strings, unsupported tap claims, broken
relative links, and privacy-indicator mutation language in supported runbooks.

## Boundaries

- Always: distinguish official API, inspected binary, local implementation,
  physical measurement, and inference.
- Ask first: deleting historical records.
- Never: call a build or unit test a physical hardware verification.

## Success Criteria

- Every repository Markdown file is classified as current, historical, research,
  internal progress, or implementation plan.
- Current docs agree on app/API/relay/contract and pinned SDK versions.
- Unsupported operator-tap and raw-JPEG persistence claims are absent from
  current runbooks.
- Historical documents retain their evidence but have an explicit status.

## Open Questions

None. Physical facts remain pending until `device-validation`.
