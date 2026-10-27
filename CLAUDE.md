# rn-maestro-smoke — notes for Claude

This repository is a Claude Code skill (and plugin) that runs Maestro smoke tests for React Native
apps and writes the results into the team's Excel test-case sheet.

## If the user wants to run a smoke test

Read [skills/rn-smoke-test/SKILL.md](skills/rn-smoke-test/SKILL.md) and follow it. The CLI is
`skills/rn-smoke-test/bin/rnsmoke` (use its absolute path as `RNSMOKE`). The React Native project
and the test-case file live elsewhere — ask for their paths if they were not given. If the user
also wants the skill available in future sessions, run `./install.sh`.

## If the user wants to change this tool

- Layout: `skills/rn-smoke-test/` is self-contained (SKILL.md, `reference/`, `templates/`,
  `bin/rnsmoke` wrapper, Python package `scripts/rnsmoke/`). `.claude-plugin/` makes the repo a
  plugin marketplace; `install.sh` symlinks the skill into `~/.claude/skills`.
- Python 3.9+, standard library + `openpyxl` only. Keep it that way (the wrapper bootstraps a venv).
- Tests: `python3 -m unittest discover -s tests -v` (no device needed). Add a test for every
  behaviour change in parsing (`testcases.py`), exporting (`report.py`) or result handling (`runner.py`).
- Keep SKILL.md, `reference/*.md` and the CLI flags in sync; Maestro syntax claims in the cheatsheet
  must be verified with `maestro check-syntax` / a real run before they are written down.
- Never commit customer test-case sheets, run results or `.env` files.
