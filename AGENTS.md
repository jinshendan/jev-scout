# Project instructions

- Keep code identifiers, comments, CLI output, API/schema names, runtime-authored report text, commit messages, issues, and PR descriptions in English. Preserve source excerpts in their original language.
- Maintain project introductions in English and Simplified Chinese: `README.md` / `README.zh-CN.md`, `docs/architecture.md` / `docs/architecture.zh-CN.md`, `docs/roadmap.md` / `docs/roadmap.zh-CN.md`, and `docs/demo.md` / `docs/demo.zh-CN.md`. Update both versions in the same PR when their content changes, and keep language-switch links visible. New project introductions need both languages. Keep status, scope, runnable commands, identifiers, limits, and claims consistent; bilingual documentation does not imply Chinese-language task parsing.
- Technical reference guides and architecture decision records may remain in English unless translation is requested. Repository About text should introduce the project in both languages.
- Keep changes aligned with the active milestone in `docs/roadmap.md`.
- Preserve a runnable offline rule baseline. Jev is a replaceable decision backend.
- Keep observations, hypotheses, and verified conclusions distinct. Do not invent benchmark results.
- Investigated source repositories remain read-only. Do not execute their code as part of the M1 investigator.
- Keep generated investigation artifacts, secrets, and private source out of version control.
- Add meaningful tests for execution boundaries, evidence preservation, and budget behavior when changing them.
- Update the README and architecture when public behavior changes.
- During authorized project development, synchronize validated checkpoints to GitHub using focused branches and descriptive PRs. Do not force-push shared branches or auto-merge PRs without user authorization.
- Do not create recurring background automations merely to synchronize Git; normal reviewed commits and pushes are the synchronization mechanism.
