# AGENTS.md — rokid-docscan-starter

Status: Current agent entrypoint for every harness (Codex, Claude and others). Updated 2026-09-30.

1. Read `.agents/progress/current.md` in full before doing anything. It holds the
   operator's decisions (§2), the verified state (§3) and the next step (§4).
2. Then read `CLAUDE.md`. It is the engineering contract for every agent, not only Claude.
3. Before designing a change, read the operator's own words. The latest Claude session for
   this repository is the newest `*.jsonl` in `~/.claude/projects/C--rokid-docscan-starter/`.
   The Codex sessions are `~/.codex/sessions/**/rollout-*.jsonl` (role `user`). The approved
   plan is `C:\Users\pupu_\.claude\plans\zany-churning-goblet.md`. Treat the operator's
   proposals as requirements.

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
