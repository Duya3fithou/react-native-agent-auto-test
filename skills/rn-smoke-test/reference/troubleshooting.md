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

Logs: `runs/<stamp>/logs/<platform>/*.log` (Maestro output), raw artifacts under
`runs/<stamp>/maestro/<platform>/<batch>/<timestamp>/<flow name>/` (commands.json, screen-hierarchy,
screenshots), Metro log `runs/metro.log`.
