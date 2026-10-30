# Maestro cheatsheet for React Native (verified on Maestro 2.10)

Validate every file with `maestro check-syntax <file>` — it catches unknown properties instantly.

## Flow anatomy

```yaml
appId: ${APP_ID}                 # injected by `rnsmoke run` (-e APP_ID=...)
name: "Login - wrong password"   # unique: the runner maps JUnit results by name
tags: [smoke, login]
---
- runFlow: ../../subflows/launch-clean.yaml
- tapOn: "Sign in"
- takeScreenshot: evidence       # the runner prefers screenshots whose name starts with "evidence"
```

Relative paths in `runFlow` resolve from the current file. Env vars: `${TEST_EMAIL}`; inline
JavaScript: `${new Date().getTime()}`, `${TEST_FACILITY && TEST_FACILITY.length > 0}`.

## Selectors

| Need | Syntax |
|---|---|
| Visible text / placeholder / accessibility label | `tapOn: "Email address"` — `text` matches text, hint (placeholder) **and** accessibility text |
| `testID` | `tapOn: { id: "login-button" }` (iOS accessibilityIdentifier, Android resource-id) |
| Regex | text is a full-match Java regex: `"(?i)invalid credentials.*"`, `"(?is)please accept.*policy.*"` |
| n-th match | `index: 1` (0-based) |
| Disambiguate label vs input with the same text | `tapOn: { text: "First name", below: { text: "First name" } }` |
| Relative | `below`, `above`, `leftOf`, `rightOf`, `childOf`, `containsChild`, `containsDescendants` |
| Point inside an element | `tapOn: { text: "...", point: "94%,50%" }` (verified) |
| Absolute point | `tapOn: { point: "50%,12%" }` |

- There is **no** `hintText:` selector key — use `text:`.
- Escape regex metacharacters from test-case copy: `. ? ( ) [ ] { } + * $ ^ |`. In double-quoted YAML
  write `\\.`; or replace dynamic parts with `.*` (`"Account not found .* Please try again\\."`).
- iOS uses typographic apostrophes (`Don’t Allow`): match with `Don.t Allow`.

## Waiting & asserting

```yaml
- extendedWaitUntil:            # the only assertion with a timeout
    visible: "Welcome.*"        # or notVisible:, or a full selector { text:, below:, ... }
    timeout: 15000
- assertVisible: "Home"         # NO timeout property in 2.10 ("Unknown Property: timeout")
- assertNotVisible:
    text: "(?i)passwords? do not match"
    above: { text: "Password" }
- waitForAnimationToEnd: { timeout: 5000 }
```
Toasts (react-native-toast-message & co.) live ~3–4 s: assert with `extendedWaitUntil` right after
the action and take the evidence screenshot immediately after the assertion.

## Input

```yaml
- tapOn: "Email address"
- inputText: "user+${new Date().getTime()}@example.com"
- inputRandomNumber         # also inputRandomText. inputRandomEmail / inputRandomPersonName are
                            # refused by the data-safety guard (they invent identities)
- eraseText: 80             # deletes BACKWARDS from the cursor
```
To clear a pre-filled field, place the cursor at the end first:
`tapOn: { text: "Email address", point: "95%,50%" }` then `eraseText`. Tapping the middle of the
field leaves trailing characters (`...@example.comcom`).

After typing into a normal (non-secure) field, `assertVisible: "<typed value>"` — it catches text that
landed in the wrong field immediately instead of three steps later. Secure fields only expose `•`;
rely on the app's own indicators (e.g. a password-rule check mark) or the final outcome.

## Keyboard

- **Avoid `hideKeyboard`.** On recent iOS simulators it is unreliable; on **Android it sends Back —
  with no keyboard open it navigates to the previous screen** (verified), and even when it closes the
  keyboard the input keeps focus, so the next scroll gesture starting on it re-opens the keyboard.
  The return key (`done`) often just focuses the next field and number pads have none.
- Use `subflows/hide-keyboard.yaml` **right after `inputText`** (keyboard guaranteed open):
  Android → `pressKey: Back`; iOS → tap `TAP_TO_DISMISS`, a static text **above** the focused field
  (its own label is ideal — `tapOn: "Phone number"` hits the label, the first match, before the
  input's placeholder; a screen title also works). Tapping a label does not blur on Android (labels
  often sit inside the input's touch area), hence the platform split.
- Never scroll or swipe with the keyboard open: a swipe that lands on Gboard types words by itself
  (gesture typing produced "Smoke by by by by...").
- An element hidden behind the keyboard still counts as visible — a tap on it hits a key instead
  (typing a stray character). Dismiss the keyboard after **every** field before tapping the next one.
- iOS "Use Strong Password?" sheet (system UI, not selectable) appears on sign-up / new-password
  fields and swallows typed text: run `rnsmoke device-setup --platform ios` once per simulator.

## Scrolling

```yaml
- scrollUntilVisible:
    element: "CREATE ACCOUNT"    # or { id: ... }
    direction: DOWN              # UP / LEFT / RIGHT
    timeout: 20000
    centerElement: true          # optional
```
`scrollUntilVisible` always swipes from the screen centre. On **Android a swipe that starts on a
single-line TextInput that already holds text does not scroll the ScrollView** (the input claims the
gesture; empty inputs are fine). On forms, use `subflows/scroll-until-visible.yaml` (env `TARGET`,
`DIRECTION`), which swipes along the left margin. Scroll far enough that the element you will tap is
well inside the screen: on Android the navigation bar covers the bottom ~100 px, and a "visible"
element at the edge may sit under it. A placeholder alone can count as visible while its label (your
`below:` anchor) is still off screen — scroll to a unique element above instead.

## Control flow & reuse

```yaml
- runFlow:
    when:
      visible: "Allow"           # also notVisible:, platform: iOS|Android, true: ${js expression}
    commands:
      - tapOn: "Allow"
- runFlow:
    file: ../../subflows/hide-keyboard.yaml
    env:
      TAP_TO_DISMISS: "SIGN UP"
- repeat:
    while: { visible: "Dismiss" }
    times: 5
    commands: [ { tapOn: "Dismiss" } ]
```

## App lifecycle

```yaml
- launchApp:
    appId: ${APP_ID}
    clearState: true          # logged-out, fresh storage (redux-persist / MMKV wiped)
    clearKeychain: true       # iOS: tokens in the keychain survive clearState otherwise
    permissions: { all: allow }
- stopApp
- openLink: "myapp://profile"   # deep links
```

## React Native specifics

| Symptom | Cause | Fix |
|---|---|---|
| Toast "Open debugger to view warnings." over bottom buttons | LogBox in debug builds | `subflows/dismiss-dev-overlays.yaml` (taps the ✕ at 94%,50% of the toast); better: test a Release build |
| Red screen "Render Error", "TypeError: ..." | JS crash | real app failure (FAIL) |
| "Could not connect to development server" / "No bundle URL present" | Metro not running | `rnsmoke metro start` (runner reports these as `error`) |
| Input already filled in debug builds | `__DEV__ ? 'someone@...' : ''` defaults | always clear fields before typing |
| Expected message "already visible" before the action | static helper text with the same copy | anchor with `above:`/`below:` + `assertNotVisible` first |
| Copy differs from source code strings | text loaded from the server / CMS | trust the live UI (`rnsmoke inspect`), not the source |
| Native date/time pickers have no accessible children | UIDatePicker / custom modals | rely on the default value or tap overlay/coordinates; note it in the flow |
| A group of views reads as one element | `TouchableOpacity` merges children into one accessibility element | tap the group by its label; read values from screenshots |
| Android: app cannot reach Metro | missing reverse port | `rnsmoke run` runs `adb reverse tcp:8081 tcp:8081` for debug builds |
| Android: form jumps back to the top when the keyboard closes | KeyboardAwareScrollView resets its offset | scroll again before tapping the next field |
| Android: the same flow fails only on one platform | layout / scrolling / keyboard behave differently | write flows once, verify on both platforms, branch with `runFlow: when: platform:` only when unavoidable |
| Android back navigation | — | `- back` (iOS has none; tap the header back button) |

## CLI reminders

```bash
maestro check-syntax flow.yaml
maestro --udid <id> hierarchy --compact   # rnsmoke inspect wraps this and filters it
maestro test --udid <id> -e APP_ID=... flow.yaml   # rnsmoke run wraps this with batching/evidence
```
