# Reclaim

Evidence-first denial recovery agent. Hackathon demo; every patient, claim, policy and payer
response is synthetic. Principles live in `.specify/memory/constitution.md`.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/001-evidence-first-denial-recovery/plan.md
<!-- SPECKIT END -->

## Spec Kit on this machine

The bash scripts cannot read `.specify/feature.json` here (the Windows `python3` shim fails and
`jq` is not installed). Prefix script calls with
`SPECIFY_FEATURE_DIRECTORY=specs/001-evidence-first-denial-recovery SPECIFY_FEATURE=001-evidence-first-denial-recovery`.
