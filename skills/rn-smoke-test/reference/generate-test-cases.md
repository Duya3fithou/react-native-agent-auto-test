# No test cases? Derive a smoke checklist from the code

Goal: 25–60 smoke cases that cover the app's critical paths, written in the team's sheet style so the
report looks like every other smoke round.

## 1. Survey

- Navigation: navigator files (`createStackNavigator`, `createBottomTabNavigator`, expo-router `app/`)
  → list of screens and how they are reached. `rnsmoke analyze` prints detected screen names.
- Auth: onboarding, sign-up, login, forgot password, logout — and their validation messages.
- Main journeys per tab: list → detail → primary action (book, buy, save, share...).
- Forms: required fields and validation order, error toasts.
- Settings / profile: view & edit details, support links, delete account (manual).
- Cross-cutting: offline / error screens, force update, permission prompts.

## 2. Write cases in the sheet style

- **Section**: feature area as users see it ("Login", "Home", "Book - Class detail", "Profile - Logout").
- **Description**: the action and its condition, one scenario per row
  ("Login with a valid email but an incorrect password").
- **Expected result**: observable outcome(s); number them when there are several
  ("1. Facility switcher is displayed  2. Upcoming bookings are listed").
- **Platform**: `App / iOS / ANDROID` unless platform-specific.
- **Test data**: account type / data needed, never real passwords.
- Mix positive and negative cases; keep each row independently executable.

## 3. Produce the checklist

Write `cases.json`:

```json
[
  {"section": "Login", "description": "Login with valid credentials",
   "expected": "Logged in and the Home screen is displayed", "test_data": "TEST_EMAIL / TEST_PASSWORD"},
  {"section": "Login", "description": "Login with a valid email but an incorrect password",
   "expected": "\"Invalid credentials\" message is displayed"}
]
```

```bash
rnsmoke template --from cases.json --out <project>/.maestro/smoke/testcases.xlsx --title "<App> Smoke Test Checklist"
rnsmoke -C <project> cases --input <project>/.maestro/smoke/testcases.xlsx
```

The generated workbook uses the standard layout (summary block on rows 1–9, header on row 10,
PASS/FAIL/PENDING dropdown, colouring), so `export` produces the usual dated result tab. Tell the user
the cases were generated and where the file is — they may want to review or extend it.
