# AGENTS.md — rokid-docscan-starter

Status: Current agent entrypoint for every harness (Codex, Claude and others). Updated 2026-10-29.

1. Read `.agents/progress/current.md` in full before doing anything. It holds the
   operator's decisions (§2), the verified state (§3) and the next step (§4).
2. Then read `CLAUDE.md`. It is the engineering contract for every agent, not only Claude.
3. Before designing a change, read the operator's own words and follow later corrections.
   Codex records are `~/.codex/sessions/**/rollout-*.jsonl` (role `user`). Discover the
   matching Claude project instead of assuming a historical path still exists. On 10/29,
   the old `C--rokid-docscan-starter` session directory and `zany-churning-goblet.md` plan
   were absent; the matching OneDrive project held memory only, with no session JSONL.
   Do not replace missing original history with a summary and call it fully verified.
   Operator proposals must be evaluated against the goal; they are not automatic adoption
   decisions. Current requirements and historical decisions are separated in
   `docs/requirements-audit.md`.

Operator constraints (2026-10-29; apply to every proposal and implementation):

- Venue operation uses only the always-on phone and glasses on its hotspot: no PC,
  no wired link, no repeated connection steps after putting the glasses on. A PC is
  a development/test tool, never a runtime dependency. Check this in independent review.
- Evaluate recording/frame selection, native stills and combinations with AI inspection,
  Work/Drive delivery and minimal HUD before subject/year benchmarks. The operator did
  not prescribe a fixed order among those improvements. Compare whole-session accuracy,
  speed and required operations before adopting a route; non-display power savings must
  not reduce accuracy/speed.
- Work means ChatGPT app/web Work. Do not ask again or substitute a PC-local task.
  Skills and historical measurements do not change these operator constraints.
- Follow the operator's corrections and changed circumstances through the conversation.
  An early proposal is a requirement to evaluate, not proof that it was adopted or remains
  current. Keep independent PC research, implementation and review moving while a separate
  manual/device action awaits approval; do not stop the whole task to reconsider one route.

Rules that past sessions broke (2026-09-29/30):

- Write what the operator told you as a fact. Never record it as "unknown" or "not
  determined". For example, the operator stopped the 4b reply and said so.
- An audit's proposal is not an operator decision. Only `current.md` §2 holds decisions.
- Do not send incomplete material to ChatGPT to test correctness.
- Sending to ChatGPT, touching the phone or glasses, and deploying to the phone each
  need the operator's approval: one yes/no with the exact command.
- PC-only work needs no question. Finish it, verify it, and report. Do not stop and wait
  while PC work remains.
- Keep `current.md` short: at most 4 lines per run. Put logs, PIDs and hashes in
  `data/device-setup/reports/`. Do not add new documents.
- Implement and audit with separate agents. Judge every change by one question: does
  ChatGPT answer correctly from the image, and can the answer be read on the glasses?
