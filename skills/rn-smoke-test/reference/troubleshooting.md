# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `doctor`: maestro missing | not installed / not on PATH | `curl -fsSL "https://get.maestro.mobile.dev" \| bash`; the wrapper also adds `~/.maestro/bin` |
| Java errors when Maestro starts | Java < 17 | `brew install openjdk@17`, set `JAVA_HOME` |
| `No ios device available` | no booted simulator | `open -a Simulator` or `xcrun simctl boot "iPhone 15"` |
| `... is not installed on ...` | wrong app id or build missing | `rnsmoke analyze`; fix with `rnsmoke init --ios-app-id ...`; install the build |
| `debug build ... Metro is not running` | debug build needs JS from Metro | `rnsmoke metro start --prewarm ios` (or install a release build) |
| First launch of a debug build times out | bundle compiled on demand | `metro start --prewarm`; first-screen wait 60–90 s in `launch-clean` |
| `error: Maestro lost the connection to the device driver` | XCTest driver hiccup | re-run with `--reinstall-driver`; reboot the simulator if it persists |
| `error: Invalid Maestro flow syntax` | unknown property / YAML mistake | `maestro check-syntax <flow>`; see cheatsheet (e.g. no `timeout` on `assertVisible`) |
| `Element not found` but it is on the screenshot | regex metacharacters, typographic apostrophe, text split across elements, label vs input | escape / `.*`, `rnsmoke inspect` to see exact strings, relative selectors |
| Tap does nothing near the bottom | keyboard or LogBox toast on top | `hide-keyboard` / `dismiss-dev-overlays` subflows |
| Typed text has leftovers | field was pre-filled and cursor in the middle | tap with `point: "95%,50%"` then `eraseText` |
| Text ends up in the previous field / stray digits (`2125550123510001`) | next field was under the keyboard, the tap hit a key | `hide-keyboard` subflow after every field, tapping a label above the field; `assertVisible` the typed value |
| Password fields stay empty, only `•` typed | iOS "Use Strong Password?" sheet | `rnsmoke device-setup --platform ios` |
| Android: flow suddenly back on the previous screen | `hideKeyboard` = Back when no keyboard is open | never use `hideKeyboard`; use the `hide-keyboard` subflow (tap a static label) |
| Android: keyboard pops up again while scrolling | the input still has focus and the swipe started on it | blur by tapping a static text while the keyboard is open (`hide-keyboard` subflow) |
| `scrollUntilVisible` stops on a half-visible input; `below:` anchor not found | placeholder counts as visible, label still off screen | scroll to a unique label above the fields with `centerElement: true` |
| Assertion on a toast is flaky | toast already gone | assert immediately with `extendedWaitUntil`, screenshot right after |
| Flow passes alone, fails in the batch | depends on state left by another flow | make it independent (`launch-clean`, explicit login) |
| Permission dialog blocks the flow | OS prompt | `permissions: {all: allow}` in `launchApp`, or `dismiss-system-dialogs` subflow |
| App shows red "Render Error" | JS exception in the app | real failure → FAIL (screenshot is the evidence) |
| Run takes very long | many flows, debug build, retries | release build, `--batch-size 15`, `--retries 0` while authoring |
| Export: "sheet changed since it was parsed" | the input file was edited after `cases` | re-run `rnsmoke cases --input ...` then `run` |
| Excel opens on an old tab | — | `export` sets the new tab active; Google Sheets import: use `--only-new-tab` |
| Need `.xls` (Excel 97-2003) | — | `export --xls` (needs LibreOffice: `brew install --cask libreoffice`) |
| `upload failed ... keeping the local link` | host unreachable / blocked by the network, file too big | retry later, try another `--host` (litterbox, imgbb), or share the run folder instead |
| Evidence links stopped working | litterbox / imgbb expiry reached | re-run `export --upload <host>` (expired links are uploaded again) or use catbox |
| `rclone remote 'rnsmoke-gdrive:' is not set up yet` | first use on this machine | `brew install rclone` then `rnsmoke rclone-setup` |
| rclone sign-in shows "This app is blocked" / access denied | the Workspace admin restricts third-party apps | use `--upload gdrive` with the company's own OAuth client |
| Google shows "500. That's an error" / "Something went wrong" during `rclone-setup` | Google-side OAuth hiccup; some browsers fail | keep the setup running and open the printed `http://127.0.0.1:53682/auth?...` link in Chrome or an incognito window; if it persists use `--upload gdrive` |
| rclone sign-in or uploads stop working later in 2026 | rclone's shared Google client is being retired (Google starts charging for it) | give rclone your own client (`client_id`/`client_secret`, then `rclone config reconnect rnsmoke-gdrive:`) or switch to `--upload gdrive` |
| rclone uploads fail with `invalid_grant` / token expired | token revoked or password changed | `rnsmoke rclone-setup --reconnect` |
| `No Google OAuth client configured` | the company's Desktop-app client JSON is neither bundled nor installed | `rnsmoke drive-login --client-file <file.json>`, or bundle it in the private repo (README: Google Drive) |
| `Not signed in to Google Drive` / sign-in timed out | no token yet, or the browser step was not finished | `rnsmoke drive-login` (add `--no-browser` to print the URL) |
| `Drive API 403` | Drive API not enabled in the Cloud project, or the consent screen is not Internal/Testing for this user | enable "Google Drive API"; add the user to the OAuth app (Internal for Workspace) |
| Teammates cannot open the Drive links | the run folder is private (default) | share `RN smoke evidence` once with the team, or export with `--share domain` |
| `--share domain needs a Google Workspace account` | personal Gmail accounts cannot share to a domain | share the folder with people/groups in Drive instead |
| `Droplr refused the credentials (HTTP 401)` | wrong email/password, or a Google/SSO-only account | set a Droplr password or use `DROPLR_TOKEN`; never put credentials in `.maestro/smoke/.env` (that file is passed to Maestro) |
| `Droplr answered without a shortlink` | the Droplr API changed (client is based on the droplr-js SDK) | the cell keeps its local link; report the listed fields so the parser in `upload.py` can be adapted |

Logs: `runs/<stamp>/logs/<platform>/*.log` (Maestro output), raw artifacts under
`runs/<stamp>/maestro/<platform>/<batch>/<timestamp>/<flow name>/` (commands.json, screen-hierarchy,
screenshots), Metro log `runs/metro.log`.
