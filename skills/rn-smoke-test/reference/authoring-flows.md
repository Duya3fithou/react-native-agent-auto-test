# Authoring flows: from a test-case row to an honest Maestro flow

A flow is evidence. When it passes, the sheet will say PASS for that row, so the flow must exercise
the row's steps and check **every observable claim** of its Expected result — nothing less, and not
something easier.

## 1. Decompose the row

| Column | Becomes |
|---|---|
| Section, Description, Test data | preconditions (logged in? which account / data state?) + steps |
| Expected result | a checklist of observable claims (numbered lists map 1:1 to assertions) |
| Platform | which platforms run it (`mark --platforms` only to override the column) |

For each claim decide: verifiable in the UI (text, element, navigation, toast, list content, field
value)? If not (email received, CRM record updated, push content, calendar entry, image quality...),
either the whole case is `manual`, or the flow covers the UI part and you mark it
`--partial "<claims not verified>"` — the sheet then shows PENDING with "verify manually: ..." even
when the automated part passes. Never silently drop a claim.

## 2. Explore before writing

1. Read the screen component: copy keys, validation order (which error fires first), what the
   button actually calls, dev-only defaults (`__DEV__ ? ... : ...`).
2. Reach the screen and dump it:
   `rnsmoke inspect --platform ios --flow <nav flow>` → element list + screenshot (Read the PNG).
   Copy often comes from a server/CMS, so the live UI wins over source strings.
3. Note what is static on the screen (titles, helper texts) — you need it for keyboard dismissal and
   for anchoring assertions.

## 3. Write the flow

```yaml
# Case     : TC-005 (Registration)
# Steps    : Register an account with a password and confirm password that do not match
# Expected : "Password do not match" message is displayed
# Note     : the helper under "Confirm password" ALWAYS reads "Passwords do not match",
#            so only the toast (rendered above the "Password" label) proves the validation fired.
appId: ${APP_ID}
name: "Registration - password mismatch"
tags: [smoke, registration]
---
- runFlow: ../../subflows/launch-clean.yaml
- runFlow: ../../subflows/go-to-sign-up.yaml
- runFlow:
    file: ../../subflows/fill-sign-up-form.yaml
    env: { PASSWORD: "Smoke#Test1", CONFIRM_PASSWORD: "Smoke#Test2" }
- assertNotVisible:                      # 1) not there before the action
    text: "(?i)passwords? do(es)? not match.*"
    above: { text: "Password" }
- tapOn: "CREATE ACCOUNT"
- extendedWaitUntil:                     # 2) appears because of the action
    visible:
      text: "(?i)passwords? do(es)? not match.*"
      above: { text: "Password" }
    timeout: 10000
- takeScreenshot: evidence               # 3) evidence at the moment of truth
```

Rules:
- **Independent flows.** Each flow sets up its own state (`launch-clean` + `login` + navigation). No
  reliance on the previous flow; the runner may reorder or re-run single flows.
- **Copy tolerance.** Test cases paraphrase. Quoted text that differs trivially (case, plural,
  punctuation, "do/does") → tolerant regex. A substantive difference (different message, missing
  element, wrong screen) → the case FAILS; do not rewrite the expectation.
- **Dynamic parts** (`{facility_name}`, dates, counts) → `.*` or the env value used in the flow.
- **No fixed sleeps** — use `extendedWaitUntil` / `waitForAnimationToEnd`.
- **Data hygiene.** Prefer read-only paths and client-side validation. When a case must create data
  (sign-up, booking), use unique values (`+${new Date().getTime()}@example.com`) on a non-production
  backend only, and say so in the header comment.
- **Credentials** only via `${VAR}` from `.env`; declare them with `mark --requires VAR1,VAR2` so the
  runner reports `blocked` (not a confusing failure) when they are missing.
- **Evidence**: `takeScreenshot: evidence` right after the decisive assertion. Extra screenshots for
  intermediate steps are fine (`takeScreenshot: step1-...`).

## 4. Layout and naming

```
.maestro/smoke/
  subflows/launch-clean.yaml        app-specific first-screen wait + overlays
  subflows/login.yaml               uses ${TEST_EMAIL}/${TEST_PASSWORD}
  subflows/go-to-<screen>.yaml      navigation helpers
  flows/<section-slug>/<case-slug>.yaml
```
`name:` = "<Section> - <short title>", unique across the suite. One flow per case is the default;
if one flow genuinely verifies several rows, mark each row with the same `--flow`.

## 5. Iterate

```bash
maestro check-syntax flows/login/wrong-password.yaml
rnsmoke mark TC-009 --flow flows/login/wrong-password.yaml --requires TEST_EMAIL,TEST_PASSWORD
rnsmoke run --platform ios --only TC-009 --run-dir latest --retries 0
rnsmoke results            # failed step, evidence path, log
```
Read the failure screenshot before changing anything. Typical flow defects: wrong selector
(label vs input), keyboard covering the target, LogBox toast covering a button, element below the
fold (needs `scrollUntilVisible`), pre-filled input, toast asserted too late. Stop after 3 failed
fix attempts and report the case as `error`/`blocked` with what you saw — do not loop forever.

## 6. Good subflows to build first

| Subflow | Purpose |
|---|---|
| `launch-clean.yaml` | `launchApp` with `clearState` + `clearKeychain` + permissions, wait for real first-screen text (debug builds: up to 60–90 s), dismiss dev overlays |
| `dismiss-dev-overlays.yaml` | LogBox warning toast in debug builds (template provided) |
| `hide-keyboard.yaml` | keyboard dismissal right after typing: Back on Android, tap `TAP_TO_DISMISS` on iOS (template provided) |
| `scroll-until-visible.yaml` | form-safe scrolling (swipes along the margin, not from the centre) with `TARGET` / `DIRECTION` (template provided) |
| `dismiss-system-dialogs.yaml` | OS permission prompts (template provided) |
| `login.yaml` | from launch to the home screen with `${TEST_EMAIL}` / `${TEST_PASSWORD}` |
| `go-to-<screen>.yaml` | tab / menu navigation reused by many cases |
