# Triage: automated vs manual vs blocked

Every row ends up in exactly one manifest status. The reason you give is written verbatim into the
Note column of the report, so keep it short and actionable.

| Status | Meaning | Sheet result |
|---|---|---|
| `automated` | a flow verifies the row (fully, or `--partial`) | PASS / FAIL from the run (partial PASS → PENDING) |
| `manual` | needs a human or an external system by nature | PENDING `[Manual] <reason>` |
| `blocked` | automatable, but a prerequisite is missing now | PENDING `[Blocked] <reason>` |
| `todo` | not looked at yet | PENDING `[Not automated] ...` |

## Always manual — data safety (never automate, never ask to bypass)

- Sign-up / registration / creating profiles or members — including negative sign-up cases ("register
  without first name", "passwords do not match"): reaching and submitting the form needs a new identity,
  and a validation regression would create a real account.
- Anything that creates or removes records: booking, waitlist, purchase, payment, order, claim, post,
  message, feedback, invite, upload, signing a waiver/agreement, delete, cancel.
- Changing or resetting the test account's password; deleting / deactivating the account.
- Anything that needs a second account.

Reason format for the Note column: `Data safety: would create an account` / `... a booking` / ...

## Usually manual

- Reading e-mail / SMS / OTP / magic links ("receive confirmation code email", "resend code").
- Push notification content and delivery; background / killed-app behaviour.
- Real payments: card entry with real cards, Apple Pay / Google Pay sheets, in-app purchases.
- Verifying a third-party system (CRM / booking back office / HQ portal content) or another device.
- Camera, photo library content, biometrics, physical sensors, audio/video quality.
- Pixel-perfect / visual design checks, animations "look right".
- Refunds, membership changes and other back-office effects.

## Usually automatable (read-only, or the session account only)

- Login / logout with the session account, wrong-password login (once per session — repeated failures
  can lock the account), navigation, tab switching, screen content present ("section X is displayed").
- Validation messages on forms whose submit cannot create data (login, search, filters).
- Lists and details (class list, profile data), search and filters.
- Opening external links / web views (assert the in-app web view or that the app left foreground).
- Idempotent edits of the session account's own fields (`--data account`): set the same value every run.
- Adding to the device calendar (in-app part only; the tap needs a reviewed `rnsmoke-safe-tap` line),
  `--partial "event appears in the Calendar app"`.

## Usually blocked until the user provides data

- No test account yet → login-dependent cases are blocked until `TEST_EMAIL` / `TEST_PASSWORD` exist.
- "User with 2 profiles", "user who booked a class", "user with an active package" → only if the ONE
  test account already is in that state (ask once). Never create the state, never use a second account;
  cases needing another state stay `blocked` ("Needs an account with ...").
- Feature flags / CMS content that must be configured, facility / tenant with specific setup.
- Platform builds that are not available (e.g. no Android build).

## Asking for data (once)

Group the blocked rows by need, e.g.

> To automate 8 more cases I need one registered test account at <facility> (TC-008..TC-015). Does it
> have 2 profiles (TC-017, TC-021) or an upcoming booking (TC-019)? I will not create either.

If the user does not answer, leave those rows `blocked` and continue.
