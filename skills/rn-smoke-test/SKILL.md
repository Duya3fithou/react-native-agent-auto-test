---
name: rn-smoke-test
description: Automated smoke / regression testing of a React Native app with Maestro, reported back into the team's Excel test-case sheet. Reads an existing checklist (.xlsx or a Google-Sheets .csv export such as "[App - X] Smoke testing.xlsx") or generates test cases from the source code, writes one Maestro flow per case, runs them on an iOS Simulator and/or Android Emulator, and exports an Excel workbook with a new tab named after today's date (DDMM) whose layout is identical to the input (Section | Description | Expected result | Actual result | Result | IOS | ANDROID | Note ...). Use when the user asks to run a smoke test, auto test, E2E / regression test, Maestro test, or to fill test results for a React Native project — including Vietnamese requests such as "chạy smoke test", "test tự động", "chạy test case", "xuất kết quả test ra excel".
argument-hint: "[rn-project-path] [test-cases.xlsx|.csv] [ios|android|both]"
---

# React Native smoke test with Maestro → Excel report

You turn a manual test-case sheet into automated Maestro flows, run them on simulators/emulators,
and hand back an Excel file with a new dated tab of results. The heavy lifting (parsing sheets,
running Maestro, collecting evidence, writing Excel) is done by the bundled `rnsmoke` CLI; your job
is the judgement: triage, exploring the UI, writing honest flows, and triaging failures.

```bash
RNSMOKE="${CLAUDE_SKILL_DIR}/bin/rnsmoke"   # if the variable is not substituted, use "<Base directory of this skill>/bin/rnsmoke"
"$RNSMOKE" --help                           # every command accepts -C <rn-project> (default: cwd)
```

The wrapper bootstraps its own Python env (openpyxl) on first use. Shell variables do not persist
between Bash calls — repeat the `RNSMOKE=...` assignment (or use the full path) in each command.

## What the user gets (the contract)

- `<project>/.maestro/smoke/runs/<stamp>/<input name> - <DDMM>.xlsx`: a copy of their workbook (all
  original tabs untouched) plus **one new tab named `DDMM`** (e.g. `2710`), cloned from the test-case
  tab — same columns, styles, widths, frozen header, dropdowns, colouring. Filled cells: Test ID (only
  if empty), Actual result, Result, IOS / ANDROID (evidence screenshot links), Note, Tester, and the
  summary block (Tested by, Test Date, Build version, Pass / Fail / Pending counters).
- Result values: **PASS** (flow passed on every platform run), **FAIL** (the app did not meet the
  expected result), **PENDING** (not verified: manual-only, blocked by missing data, automation error,
  or no flow yet — the reason is in Note).
- Reusable assets in `<project>/.maestro/smoke/`: `flows/`, `subflows/`, `manifest.json` (case ↔ flow),
  `config.json`. These are meant to be committed to the app repo (re-runs then skip straight to
  run → export); `runs/`, `.env` and `cases.json` are git-ignored.

## Data safety — absolute, overrides everything below

A smoke session may change the data of **exactly one test account** (the one in `.maestro/smoke/.env`:
`TEST_EMAIL` / `TEST_PASSWORD`, or `TEST_USERNAME` / `TEST_PHONE`) and **nothing else**. Missing coverage
is acceptable; junk data in the client's system is not.

- **Never create accounts or profiles**: no sign-up / registration submit, no "add profile/member/child",
  no new, random or timestamped e-mails (`+${Date}`, `inputRandomEmail`), not even to reach a form "only
  to test validation" — a validation regression would create a real account.
- **Never create or remove records**: bookings, waitlists, purchases, payments, orders, claims, posts,
  messages, feedback, invites, uploads, signed waivers/agreements, deletions, cancellations.
- **Never change the test account's password or identity, and never delete or deactivate it.**
- **Allowed**: reading anything; signing in/out with the session account; idempotent edits of that
  account's own fields (same value every run, flow marked `--data account`).
- **One account per session**: no second account, no `TEST_EMAIL_2` / admin credentials. `rnsmoke`
  drops extra account variables and refuses a different account in the same run.
- Cases that need any of the forbidden actions are `manual` with the reason
  `Data safety: <what it would create/change>` — do not ask the user for permission to bypass this.
- Enforced by code: `run`, `mark --flow` and `inspect --flow` scan every flow and subflow
  (`scripts/rnsmoke/safety.py`) and refuse violations; there is no switch to disable it. Do not look for
  ways around it, and **never run `maestro test` directly against the app** — always through `rnsmoke`.
  A tap the guard misreads (a bottom tab named "Book", a date-picker overlay tapped by coordinates)
  may be declared harmless with `# rnsmoke-safe-tap: "<label>" -- <reason>` in that flow, only when it
  provably changes no server data; every such line is listed by `status` for human review.

## Non-negotiable rules

1. **Never fabricate a result.** PASS only comes from a Maestro flow that ran in this session and
   whose assertions encode the case's Expected result. `rnsmoke set-result` deliberately cannot set PASS.
2. **Never weaken an assertion to make a case pass.** If the app behaves differently from Expected
   result, the case is FAIL — record what the app actually did.
3. **Assertions must be caused by the action.** If the expected text could already be on screen
   (helper text, previous toast), `assertNotVisible` it before the action and/or anchor it with a
   relative selector (`above:` / `below:`). Trivially-true flows are worse than no flow.
4. **Read-only on the app.** Do not modify the React Native source, native config or env files to make
   tests work. Missing `testID`s, flaky screens, dev-only defaults → work around them in flows and
   mention them in the final report as suggestions.
5. **No secrets in flows.** Credentials and test data live in `.maestro/smoke/.env` and are referenced
   as `${VAR}`; never echo their values back.
6. **Data safety (above) is absolute.** Beyond it, no irreversible side effects without explicit
   approval: messaging real people, publishing evidence to a public file host. Test against
   dev/staging builds unless the user says otherwise.
7. **Ask once, then run autonomously.** Collect missing inputs in a single question round at the
   start; afterwards keep going and post short progress updates (section done, X/Y passing).
8. Never overwrite the user's input file; never hand-edit `results-*.json` or `cases.json`.

## Workflow

### Re-run fast path — check this first

If `<project>/.maestro/smoke/manifest.json` exists and, after `cases`, `status` shows at least one
`automated` case, the flows were written in an earlier round (usually committed to the app repo). This is
a **re-run**: do NOT triage, explore the UI or write flows — those are the slow, expensive steps and they
are already done. Only:

```bash
test -f <project>/.maestro/smoke/manifest.json && echo "re-run: use the fast path"
"$RNSMOKE" doctor                                          # + device-setup once on a new simulator
"$RNSMOKE" -C <project> cases --input "<sheet>"            # relinks the saved flows; prints Coverage
"$RNSMOKE" -C <project> status                             # automated / manual / blocked / todo
#   app on the device: step 4 (Metro only for debug builds)
"$RNSMOKE" -C <project> run --platform ios                 # Bash run_in_background
"$RNSMOKE" -C <project> run --platform android --run-dir latest   # if both platforms (can run in parallel)
"$RNSMOKE" -C <project> export                             # + --upload gdrive if the user wants Drive links
```
- Inputs (step 0): ask only for what is missing — sheet, platform(s), build. Test data comes from the
  existing `.maestro/smoke/.env`.
- Failures: step 8 applies, but only to fix flows broken by an app/UI change (max 3 attempts per flow);
  real app failures stay FAIL.
- `todo` cases (new rows, or rows edited too much to relink): leave them PENDING `[Not automated]`. In the
  final message give their count and ids and offer to automate them as a separate, slower job (steps
  5–6) — start it only if the user asks.
- Cases relinked to an edited row (`status`: "relinked from ...") run as they are; list them in the final
  message so someone checks the flow still matches the new wording.
- `manual` / `blocked` stay as they are; if the user now provides the missing test data (e.g. accounts),
  say which blocked cases could be automated next.

No manifest, or no automated case yet → first round: follow steps 0–9.

### 0. Inputs

Needed: React Native project path · test-case file (.xlsx/.csv) **or** "none" · platform(s)
(default: iOS when on macOS, else Android) · **one** dedicated test account on a dev/staging backend
(`TEST_EMAIL` + `TEST_PASSWORD` in `.maestro/smoke/.env`) · which build/environment.
If the project path or test-case file is unclear, ask (one AskUserQuestion round, include the test
account question). Without credentials, continue: credential-dependent cases become `blocked`.
Never ask for a second account.

### 1. Environment

```bash
"$RNSMOKE" doctor                 # python/openpyxl, Java 17+, Maestro, Xcode + booted simulator, adb + emulator
```
Fix blocking items: Maestro → `curl -fsSL "https://get.maestro.mobile.dev" | bash`; boot a
simulator → `open -a Simulator` / `xcrun simctl boot "iPhone 15"`; emulator → `emulator -avd <name>`.
Then, once per simulator: `"$RNSMOKE" device-setup --platform ios` — turns off iOS "Suggest Strong
Passwords", whose system sheet otherwise swallows text typed into sign-up / password forms.

### 2. Project + workspace

```bash
"$RNSMOKE" -C <project> analyze   # app ids, schemes/flavors, scripts, which build is installed (debug/release)
"$RNSMOKE" -C <project> init      # creates .maestro/smoke, auto-detects app ids (verify!)
"$RNSMOKE" -C <project> init --ios-app-id <bundle id> --android-app-id <package>   # to correct them
```

### 3. Test cases

- **File given:** `"$RNSMOKE" -C <project> cases --input "<file>" [--sheet <tab>]`. Check the printed
  sheet, header row and column mapping. Workbooks often keep history tabs: the parser picks the
  visible/active test-case tab — confirm it is the current checklist, otherwise pass `--sheet`.
- **No file:** follow [reference/generate-test-cases.md](reference/generate-test-cases.md), then
  `"$RNSMOKE" template --from cases.json --out <project>/.maestro/smoke/testcases.xlsx --title "<App> Smoke Test Checklist"`
  and parse that file with `cases --input`.

### 4. App on the device

See [reference/build-and-install.md](reference/build-and-install.md). Prefer the build the user wants
tested; a Release build (bundled JS, no dev overlays) is the most reliable. For debug builds:
`"$RNSMOKE" -C <project> metro start --prewarm ios` (stop it at the end with `metro stop`).

### 5. Triage every case

Read [reference/triage-rules.md](reference/triage-rules.md). Bulk-mark what cannot be automated, with a
reason that will appear verbatim in the Note column. Apply **Data safety** first: every case that would
create an account or a record, or change anything but the session account, is `manual`:

```bash
"$RNSMOKE" -C <project> mark --section Registration --manual "Data safety: would create an account"
"$RNSMOKE" -C <project> mark TC-051 TC-052 --manual "Data safety: would create a booking"
"$RNSMOKE" -C <project> mark TC-001 TC-007 --manual "Needs the confirmation-code email"
"$RNSMOKE" -C <project> mark --section "E2E Purchase" --manual "Data safety: real payment"
"$RNSMOKE" -C <project> mark TC-008..TC-011 --blocked "Needs TEST_EMAIL / TEST_PASSWORD"
"$RNSMOKE" -C <project> status          # coverage per section, TODO list, problems
```
Cases that depend on a data state (an existing booking, two profiles...) run only if the single test
account already has that state — ask the user once what state the account is in; never create it.
Otherwise `blocked` with the missing state as the reason.

### 6. Author flows (section by section)

Read [reference/authoring-flows.md](reference/authoring-flows.md) and
[reference/maestro-rn-cheatsheet.md](reference/maestro-rn-cheatsheet.md) first. Loop per case:

1. Read the screen's source (copy, validation order, navigation) and explore the live UI:
   `"$RNSMOKE" -C <project> inspect --platform ios [--flow <flow that reaches the screen>]` — prints every
   element with text / id / accessibility label and saves a screenshot (Read it).
2. Build shared subflows first (`subflows/`): launch-clean (wait for real first-screen text),
   dismiss-dev-overlays, hide-keyboard, scroll-until-visible, login, go-to-<screen>. When reporting
   both platforms, run every new flow on both: keyboard, scrolling and layout differ (see cheatsheet).
3. Write `flows/<section-slug>/<case-slug>.yaml`: header comment (case id, steps, expected), unique
   `name:`, `appId: ${APP_ID}`, one assertion per observable claim, `takeScreenshot: evidence` when
   the expected result is on screen. Validate with `maestro check-syntax <file>`.
4. Link it: `"$RNSMOKE" -C <project> mark TC-012 --flow flows/login/wrong-password.yaml [--requires TEST_EMAIL,TEST_PASSWORD] [--data account] [--partial "<what is not verified>"]`
   — refused if the flow breaks Data safety. `--data account` only for idempotent edits of the session
   account's own fields.
5. Run it right away: `"$RNSMOKE" -C <project> run --platform ios --only TC-012 [--run-dir latest] --retries 0`
   then fix flow problems until it passes or you have confirmed a real app failure (step 8).

Scale: authoring is the slow part (a large checklist can take hours the first time; later sprints
reuse the flows). Follow the sheet's section order unless the user names priorities, report after
each section ("Login: 4/4 automated, 3 pass, 1 fail"), and remember `export` works at any point —
whatever is not automated yet is reported as PENDING, never guessed.

### 7. Full run

```bash
"$RNSMOKE" -C <project> run --platform ios                        # new run dir; batches of 10 flows
"$RNSMOKE" -C <project> run --platform android --run-dir latest   # second platform into the same run
```
A flow takes ~0.5–2 min; for more than ~5 flows start the command with Bash `run_in_background` and
wait for the completion notification (progress: `runs/<stamp>/progress-<platform>.log`).

### 8. Triage failures (max 3 fix attempts per flow)

`"$RNSMOKE" -C <project> results` lists fail/error cases with failed step, log and evidence. For each:
Read the failure screenshot, the step, and (if needed) the `screen-hierarchy/*.json` next to it, then:

| Finding | Action |
|---|---|
| Flow defect (selector, timing, keyboard, overlay, wrong precondition) | fix the flow → `run --failed --run-dir latest` |
| App behaves differently from Expected result | keep FAIL; if the message is cryptic: `set-result TC-x --platform ios --status fail --message "<what the app did>"` |
| Environment / data problem (backend down, account lacks state) | `set-result ... --status blocked --message "<what is missing>"` |
| Infrastructure (`error`: driver, Metro, app not launchable) | fix the environment, re-run; never report as FAIL |

Then run the whole suite once more if flows changed substantially, so the final numbers come from
one consistent run.

### 9. Export and report

```bash
"$RNSMOKE" -C <project> export [--tester "<name>"] [--only-new-tab] [--xls]
```
`--only-new-tab` writes a workbook with just the dated tab (easy "Import → Insert new sheet" into
Google Sheets); `--xls` additionally converts to legacy .xls via LibreOffice. The command re-reads the
file and prints the counts. Stop Metro if you started it.

Shareable evidence links (only when the user asks for them). Use the company's **Google Drive** with the
team's own OAuth client: private by default, least-privilege `drive.file`, deletable. The tool signs in by
itself (browser on first use — tell the user to expect it; token stored and refreshed automatically). The
client is bundled as `google-oauth-client.json` in this skill, or `"$RNSMOKE" drive-login` picks up a
downloaded `client_secret_*.json` from ~/Downloads (README explains how to create one in ~10 minutes).
```bash
"$RNSMOKE" -C <project> upload --dry-run                      # what would be uploaded (no network)
"$RNSMOKE" -C <project> export --upload gdrive                # private: owner + people the folder is shared with
"$RNSMOKE" -C <project> export --upload gdrive --share domain # whole company can view (only if the user wants it)
```
Alternatives: `--upload rclone` (rclone's shared Google client is being retired in 2026). Public free hosts
(`catbox`, `litterbox --expire 72h`, `imgbb`) and the experimental `droplr` publish client screenshots — only
on explicit request; never `--share anyone` on your own initiative. URLs replace the local paths in the
IOS / ANDROID cells; links are cached in `runs/<stamp>/uploads.json`; a failed upload keeps the local link.
Tell the user where the files went and who can open them.

Final message to the user, in their language: output path (and that evidence links are relative to
it — share the whole run folder), PASS / FAIL / PENDING counts, each FAIL with a one-line reason and
its evidence file, PENDING grouped by reason with what would unblock them, where the flows live, and
how to re-run next sprint.

## Next sprint

Use the **Re-run fast path** at the top of the workflow. `cases --input <new sheet>` keeps flows linked by
content and relinks lightly edited cases. Tell the user to commit `<project>/.maestro/smoke/` (flows,
subflows, `manifest.json`, `config.json`) to the app repo so every tester and machine reuses the flows;
`.env`, `runs/` and `cases.json` stay local (git-ignored).

## Reference

- [reference/maestro-rn-cheatsheet.md](reference/maestro-rn-cheatsheet.md) — Maestro syntax verified on 2.10 + React Native gotchas
- [reference/authoring-flows.md](reference/authoring-flows.md) — turning a test-case row into an honest flow
- [reference/triage-rules.md](reference/triage-rules.md) — automated vs manual vs blocked
- [reference/build-and-install.md](reference/build-and-install.md) — getting the right build onto a simulator/emulator
- [reference/generate-test-cases.md](reference/generate-test-cases.md) — no test cases? derive them from the code
- [reference/troubleshooting.md](reference/troubleshooting.md) — symptom → fix
- `templates/` — subflows and an annotated example flow (copied into the workspace by `init`)
