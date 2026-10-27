# Triage: automated vs manual vs blocked

Every row ends up in exactly one manifest status. The reason you give is written verbatim into the
Note column of the report, so keep it short and actionable.

| Status | Meaning | Sheet result |
|---|---|---|
| `automated` | a flow verifies the row (fully, or `--partial`) | PASS / FAIL from the run (partial PASS → PENDING) |
| `manual` | needs a human or an external system by nature | PENDING `[Manual] <reason>` |
| `blocked` | automatable, but a prerequisite is missing now | PENDING `[Blocked] <reason>` |
| `todo` | not looked at yet | PENDING `[Not automated] ...` |

## Usually manual

- Reading e-mail / SMS / OTP / magic links ("receive confirmation code email", "resend code").
- Push notification content and delivery; background / killed-app behaviour.
- Real payments: card entry with real cards, Apple Pay / Google Pay sheets, in-app purchases.
- Verifying a third-party system (CRM / booking back office / HQ portal content) or another device.
- Camera, photo library content, biometrics, physical sensors, audio/video quality.
- Pixel-perfect / visual design checks, animations "look right".
- Irreversible actions on shared accounts: delete account, cancel membership, refund
  (automate only with a throwaway account the user explicitly provides).

## Usually automatable (if data exists)

- Form validation messages, required fields, toasts and inline errors.
- Login / logout / navigation, tab switching, screen content present ("section X is displayed").
- Lists and details (class list, profile data), search and filters.
- Opening external links / web views (assert the in-app web view or that the app left foreground).
- Signature pads (`swipe` across the canvas) — mark `--partial` if the stored image matters.
- Adding to calendar: automate the in-app part, `--partial "event appears in the Calendar app"`.

## Usually blocked until the user provides data

- "User with 2 profiles", "user who booked a class", "user with an active package" → one account
  per state, in `.env` (`TEST_EMAIL_TWO_PROFILES`, ...). Ask once with the full list of needs.
- Feature flags / CMS content that must be configured, facility / tenant with specific setup.
- Platform builds that are not available (e.g. no Android build).

## Asking for data (once)

Group the blocked rows by need, e.g.

> To automate 14 more cases I need: (1) a registered account at <facility> — TC-008..TC-015;
> (2) an account with 2 profiles — TC-017, TC-021; (3) an account with an upcoming booking — TC-019.
> Put them in `.maestro/smoke/.env` or tell me and I will.

If the user does not answer, leave those rows `blocked` and continue.
