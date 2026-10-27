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
  `config.json`. These are meant to be committed; `runs/` and `.env` are git-ignored.

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
6. **No irreversible side effects without explicit approval:** real purchases, deleting/cancelling
   accounts or memberships, messaging real people, creating data in production, publishing evidence
   to a public file host. Mark such cases `manual` (or ask once). Test against dev/staging builds
   unless the user says otherwise.
7. **Ask once, then run autonomously.** Collect missing inputs in a single question round at the
   start; afterwards keep going and post short progress updates (section done, X/Y passing).
8. Never overwrite the user's input file; never hand-edit `results-*.json` or `cases.json`.

## Workflow

### 0. Inputs

Needed: React Native project path · test-case file (.xlsx/.csv) **or** "none" · platform(s)
(default: iOS when on macOS, else Android) · test accounts / data · which build/environment.
If the project path or test-case file is unclear, ask (one AskUserQuestion round, include the test
account question). Without credentials, continue: credential-dependent cases become `blocked`.

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
reason that will appear verbatim in the Note column:

```bash
"$RNSMOKE" -C <project> mark TC-001 TC-007 --manual "Needs the confirmation-code email"
"$RNSMOKE" -C <project> mark --section "E2E Purchase" --manual "Real payment"
"$RNSMOKE" -C <project> mark TC-008..TC-011 --blocked "Needs TEST_EMAIL / TEST_PASSWORD"
"$RNSMOKE" -C <project> status          # coverage per section, TODO list, problems
```
If several cases need the same missing data (an account with a booking, two profiles...), list the
needs and ask the user once; put answers into `.maestro/smoke/.env`.

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
4. Link it: `"$RNSMOKE" -C <project> mark TC-012 --flow flows/login/wrong-password.yaml [--requires TEST_EMAIL,TEST_PASSWORD] [--partial "<what is not verified>"]`
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

`cases --input <new sheet>` keeps flows linked by content and relinks lightly edited cases (flagged for
review in `status`). Author flows only for new TODO cases, then `run` → `export`.

## Reference

- [reference/maestro-rn-cheatsheet.md](reference/maestro-rn-cheatsheet.md) — Maestro syntax verified on 2.10 + React Native gotchas
- [reference/authoring-flows.md](reference/authoring-flows.md) — turning a test-case row into an honest flow
- [reference/triage-rules.md](reference/triage-rules.md) — automated vs manual vs blocked
- [reference/build-and-install.md](reference/build-and-install.md) — getting the right build onto a simulator/emulator
- [reference/generate-test-cases.md](reference/generate-test-cases.md) — no test cases? derive them from the code
- [reference/troubleshooting.md](reference/troubleshooting.md) — symptom → fix
- `templates/` — subflows and an annotated example flow (copied into the workspace by `init`)
