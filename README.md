# rn-maestro-smoke

**English** | [Tiếng Việt](README.vi.md)

A **Claude Code** skill that runs **automated smoke tests** for **React Native** apps with **Maestro** and
exports the results to an **Excel file** with **one new tab named after the test date** (`DDMM`, e.g. `2710`),
in exactly the same layout as your original test-case sheet (`Test ID | Platform | Section | Description |
Expected result | Actual result | Result | IOS | ANDROID | Test data | Note | Tester`).

All you give Claude is: **the link to this repo**, **the React Native source code**, and **the test-case file**
(`.xlsx`, a `.csv` exported from Google Sheets, or nothing at all — Claude then generates test cases from the code).

```
Test cases (.xlsx/.csv) ──► Claude reads the cases + app code ──► writes one Maestro flow per case
        │                                                                  │
        └──────── Excel file + "DDMM" tab ◄── results + evidence screenshots ◄── runs on Simulator/Emulator
```

---

## 1. Quick start (recommended)

Open Claude Code anywhere and paste a prompt (adjust the paths):

```text
Clone https://github.com/Duya3fithou/react-native-agent-auto-test into ~/tools/rn-maestro-smoke and run ./install.sh.
Then use the rn-smoke-test skill to smoke test the React Native app in ~/projects/my-app
with the test-case file "~/Downloads/[App - MyApp] Smoke testing.xlsx" on the iOS simulator.
Test account: email ... / password ... (if any).
```

Variations:

| Situation | Prompt |
|---|---|
| `.csv` exported from Google Sheets | `... with the test-case file "~/Downloads/[App - MyApp] Smoke testing - app.csv"` |
| No test cases | `... the app in ~/projects/my-app has no test cases yet, create a smoke test suite and run it` |
| Both iOS and Android | `... run on both the iOS simulator and the Android emulator` |
| Next time (skill installed) | `/rn-smoke-test ~/projects/my-app ~/Downloads/smoke.xlsx ios` (installed as a plugin: `/rn-maestro-smoke:rn-smoke-test ...`) — or simply say "run a smoke test ..." |

Prompts in Vietnamese work just as well.

Claude will: check the environment → analyze the project → read the test cases → triage which cases can be
automated → explore the real UI on the simulator → write Maestro flows → run them and fix broken flows (never
"fixing" a flow to hide an app bug) → export the Excel file → report PASS/FAIL/PENDING with reasons.

## 2. What you get

`<project>/.maestro/smoke/runs/<date_time>/`

| File | Contents |
|---|---|
| `<original file name> - 2710.xlsx` | The whole original workbook (existing tabs untouched) + a **new `2710` tab** cloned from the test-case tab: same columns, styles, widths, frozen header, dropdowns, colouring |
| `evidence/ios/TC-xxx.png`, `evidence/android/...` | Screenshots taken at the moment of verification (linked from the IOS / ANDROID columns) |
| `results-ios.json`, `logs/`, `maestro/` | Detailed results, logs and raw Maestro artifacts |

In the new tab:

| Column | Value |
|---|---|
| **Result** | `PASS` — the flow ran and every claim in *Expected result* was checked · `FAIL` — the app did not meet *Expected result* · `PENDING` — not verified (reason in Note) |
| **Actual result** | `As expected`, or a description of what the app actually did |
| **Note** | `[Auto] Maestro iOS: PASS in 42s`, `[Manual] Needs the confirmation-code email`, `[Blocked] Needs TEST_EMAIL`... |
| **Test ID** | Filled with `TC-001...` when the column is empty (to match the evidence files) |
| Summary block | Tested by, Test Date, Build version (read from the installed app), Pass / Fail / Pending counts, total cases |

> By default evidence links are relative paths — when sharing, send **the whole run folder** (or a zip of it),
> or upload the evidence to Google Drive (below).
> To import into Google Sheets: `rnsmoke export --only-new-tab`, then *File → Import → Insert new sheet(s)*.
> Need the legacy `.xls` format (Excel 97-2003)? `rnsmoke export --xls` (requires LibreOffice).

### Evidence links for the whole team — Google Drive (recommended)

Evidence screenshots/videos are uploaded to **the Google Drive of the person running the tests**
(`RN smoke evidence/<sheet name>/<run>`), and `drive.google.com/file/d/...` links are written into each cell of the
IOS / ANDROID columns (just like the old sheet).

- **Least privilege (`drive.file`)**: the tool can only see the files it created — nothing else in your Drive.
- **Private by default**: only you and the people the folder is shared with can open the links (share
  `RN smoke evidence` with your team once and you are done); `--share domain` = everyone in the company can view.
- The tool performs the OAuth sign-in itself (browser, PKCE); the token is stored in `~/.rnsmoke/google-token.json`
  (mode 600) and refreshed automatically. Revoke access at myaccount.google.com/permissions.

**Create the OAuth client — once for the whole team, anyone can do it (~10 minutes, no Workspace admin rights needed)**
1. Create a project: <https://console.cloud.google.com/projectcreate> (any name, e.g. `rnsmoke`).
2. Enable the Drive API: <https://console.cloud.google.com/apis/library/drive.googleapis.com> → **Enable**.
3. Consent screen: <https://console.cloud.google.com/auth/overview> → *Get started* → App name `rnsmoke`, support email →
   Audience **Internal** (company Google Workspace accounts) → contact email → *Create*.
   If Internal is not available: choose **External**, then click **Publish app** under *Audience* (the `drive.file`
   scope does not require Google verification; in *Testing* mode tokens expire after 7 days).
4. Create the client: <https://console.cloud.google.com/auth/clients/create> → Application type **Desktop app** →
   *Create* → **Download JSON** (a `client_secret_….json` file in your Downloads folder).

**Usage**
```bash
R=~/tools/rn-maestro-smoke/skills/rn-smoke-test/bin/rnsmoke
$R drive-login                                           # finds client_secret_*.json in Downloads → browser → Allow
$R -C <project> upload --dry-run                         # preview which files would be uploaded (no network)
$R -C <project> export --upload gdrive                   # Excel with Drive links in the IOS / ANDROID columns (private)
$R -C <project> export --upload gdrive --share domain    # everyone in the company can open the links
```
`drive-login` looks for the client in this order: `~/.rnsmoke/`, `skills/rn-smoke-test/google-oauth-client.json`,
`resource/client_secret_*.json` in the repo, then `~/Downloads/client_secret_*.json`.
To spare the team from passing the file around: save the client as `skills/rn-smoke-test/google-oauth-client.json` and
`git add -f` it into a **private repo** (`.gitignore` blocks this file by default; Google does not treat the client
secret of a Desktop app as confidential).
Links are cached in `runs/<date_time>/uploads.json`, so exporting again never uploads duplicates; if Drive fails, that
cell keeps its local link and the Excel file is still produced.

<details>
<summary>Alternatives: rclone, public hosts</summary>

- `--upload rclone` (after `brew install rclone` + `rnsmoke rclone-setup`): same Drive folder layout. rclone's shared
  Google client is being retired in 2026 (Google is starting to charge for it) and its sign-in may fail (Google 500)
  — configure rclone with your own client instead.
- Free public hosts — **do not use for client apps**: `catbox` (permanent, anonymous uploads cannot be deleted),
  `litterbox --expire 72h` (self-deleting), `imgbb` (needs `IMGBB_API_KEY`), `droplr` (experimental, old SDK,
  unverified).
</details>

## 3. Machine requirements

| Component | Notes |
|---|---|
| macOS + Xcode + one booted iOS Simulator | for iOS (`open -a Simulator`) |
| Android SDK + emulator | for Android (`emulator -avd <name>`) |
| Java 17+ | required by Maestro (`brew install openjdk@17`) |
| [Maestro CLI](https://maestro.mobile.dev) | `curl -fsSL "https://get.maestro.mobile.dev" \| bash` — Claude installs it if missing |
| Python 3.9+ | the wrapper creates a venv with `openpyxl` in `~/.rnsmoke/venv` if needed |
| Node + the app's dependencies | only needed to build the app or run Metro for debug builds |

Quick check: `skills/rn-smoke-test/bin/rnsmoke doctor`

## 4. Installation

**Option A — script (recommended):**
```bash
git clone https://github.com/Duya3fithou/react-native-agent-auto-test ~/tools/rn-maestro-smoke
~/tools/rn-maestro-smoke/install.sh          # symlinks the skill into ~/.claude/skills/rn-smoke-test
```
`git pull` is all it takes to update (it is a symlink). Use `--copy` to copy instead of symlinking, and
`--project <path>` to install for a single project.

**Option B — Claude Code plugin marketplace:**
```text
/plugin marketplace add Duya3fithou/react-native-agent-auto-test
/plugin install rn-maestro-smoke@rn-maestro-smoke
```

**Option C — no install:** open Claude Code inside this repo folder (`CLAUDE.md` tells Claude what to do).

## 5. Data safety & test data

**A smoke session changes the data of exactly ONE test account and nothing else.** Missing coverage is acceptable;
junk data in your system is not.

- Provide **one** dedicated test account on a dev/staging backend in `<project>/.maestro/smoke/.env`
  (`TEST_EMAIL` / `TEST_PASSWORD`; template: `.env.example`). The file is git-ignored; flows never contain passwords.
  Any other account variable (`TEST_EMAIL_2`, `ADMIN_PASSWORD`...) is ignored, and a run refuses to switch accounts.
- **Never automated** (reported `PENDING [Manual] Data safety: ...`): sign-up / registration — including negative
  sign-up cases, because reaching and submitting the form needs a new e-mail and a validation bug would create a real
  account — adding profiles, bookings, waitlists, purchases, payments, claims, posts, feedback, uploads, signing
  waivers, deleting or cancelling anything, changing the account's password, deleting the account.
- **Allowed**: reading screens, signing in/out with the test account, idempotent edits of that account's own fields.
- **Enforced in code, cannot be switched off**: before anything runs, `rnsmoke` scans every flow and subflow and
  refuses flows that type another identity (another e-mail, `+timestamp` addresses, random names), tap
  create/register/delete-account or record-creating buttons (book, buy, submit, send, post, add, delete...), or call
  APIs from scripts. Refused cases are not run and the reason goes into the Note column. A tap the guard misreads (a
  tab called "Book") can be declared harmless in the flow file — `rnsmoke status` lists every such line for review.
- Cases that need a data state (2 profiles, a booked class...) run only if the single test account already has it;
  Claude asks once and never creates it.
- Claude **does not modify the app's source code**.

## 6. Folder inside the React Native project

```
<project>/.maestro/smoke/
  config.json        app ids for iOS/Android, Metro port
  manifest.json      each test case → flow / manual / blocked (+ reason)
  cases.json         the most recently parsed test cases (git-ignored)
  flows/<section>/   one Maestro flow per case                   ← commit these
  subflows/          clean launch, login, hide keyboard...        ← commit these
  .env               test data (git-ignored)
  runs/              results of each run (git-ignored)
```
**Commit `.maestro/smoke/` to the app repo** (the git-ignored `.env`, `runs/` and `cases.json` stay local). Every
tester and machine then reuses the flows: the next round goes straight to *run → export* — no triage, no UI
exploration, no flow writing. Lightly edited cases are relinked automatically; new cases are reported as
`PENDING [Not automated]` and Claude offers to automate them as a separate job.

## 7. CLI commands (Claude uses them; you can run them by hand too)

```bash
R=~/tools/rn-maestro-smoke/skills/rn-smoke-test/bin/rnsmoke
$R doctor                                         # check the environment
$R device-setup --platform ios                    # turn off "Suggest Strong Passwords" on the simulator (once)
$R -C <project> analyze                           # app ids, schemes/flavors, installed app (debug/release)
$R -C <project> init                              # create .maestro/smoke
$R -C <project> cases --input <file.xlsx|.csv>    # read the test cases
$R -C <project> status                            # automation coverage per section
$R -C <project> mark TC-004 --flow flows/registration/x.yaml
$R -C <project> mark TC-001 --manual "Needs the OTP email"
$R -C <project> inspect --platform ios            # list on-screen elements + screenshot
$R -C <project> metro start --prewarm ios         # for debug builds
$R -C <project> run --platform ios                # run (batches of 10 flows, failed flows retried)
$R -C <project> results                           # summary of failures/errors with evidence
$R -C <project> export                            # export Excel with the DDMM tab
$R -C <project> upload --dry-run                  # preview which evidence files would be uploaded
$R drive-login                                    # once: sign in to Google Drive (team OAuth client)
$R -C <project> export --upload gdrive            # export Excel with evidence links on Google Drive
```

## 8. Known limits

- Cannot be verified automatically: email/SMS/OTP content, push notifications, real payments, data in external
  systems (CRM, back-office), camera/biometrics → `PENDING [Manual]`.
- **Release** builds give the most stable results; debug builds need Metro and show LogBox overlays (the skill
  handles them).
- Each flow takes ~0.5–2 minutes; writing flows for a 100+ case suite takes the most time the first time, later
  sprints only re-run them.

## 9. Development

```bash
python3 -m unittest discover -s tests -v     # 100% offline, no device needed
```
Layout:
```
.claude-plugin/            plugin.json + marketplace.json
skills/rn-smoke-test/
  SKILL.md                 the workflow Claude follows
  reference/               Maestro cheatsheet for RN, writing flows, triaging cases, building the app, troubleshooting
  templates/               subflow templates, example flow, device setup
  bin/rnsmoke              wrapper (bootstraps its Python env)
  scripts/rnsmoke/         Python package: parse sheets, run Maestro, export Excel, upload evidence
tests/                     unit tests with synthetic data
examples/                  sample checklist (fake data)
install.sh
```
