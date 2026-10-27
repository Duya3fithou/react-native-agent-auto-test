# Getting the right build onto a simulator / emulator

`rnsmoke analyze` tells you which candidate app ids are installed on booted devices and whether the
installed build is **debug** (loads JS from Metro) or **release** (bundled JS).

## Decide what to test

1. The user named a build / environment → install exactly that.
2. A build of the app is already installed and the user did not ask for another → use it, but report
   its version/build (it is written into "Build version" of the report).
3. Nothing installed → build from source (below) for the environment the user wants (staging/dev by
   default, never production data without explicit approval).

Release builds are preferred for smoke tests: no Metro dependency, no LogBox overlays, closer to
production, faster. Debug builds work too (`rnsmoke metro start --prewarm ios`).

## Provided binaries

| File | Install |
|---|---|
| iOS simulator build `.app` (or `.tar.gz` from EAS) | `xcrun simctl install booted path/App.app` |
| `.ipa` | device-only — cannot run on a simulator; ask for a simulator build |
| `.apk` | `adb install -r app.apk` |
| `.aab` | `bundletool build-apks --connected-device --bundle app.aab --output app.apks && bundletool install-apks --apks app.apks` |

## Build from source — React Native CLI

Follow the project's own scripts first (`package.json` scripts, README, env switch scripts such as
`switch_env.sh` / react-native-config `.env.*`). Generic recipes:

```bash
# JS deps
yarn install            # or npm ci / pnpm install, matching the lockfile

# iOS (simulator)
cd ios && (bundle exec pod install || pod install) && cd ..
npx react-native run-ios --simulator "iPhone 15" --mode Release          # add --scheme "<Scheme>" if several
# or explicitly:
xcodebuild -workspace ios/<App>.xcworkspace -scheme "<Scheme>" -configuration Release \
  -sdk iphonesimulator -derivedDataPath build/ios
xcrun simctl install booted build/ios/Build/Products/Release-iphonesimulator/<App>.app

# Android (emulator)
npx react-native run-android --mode=<flavor>Release        # e.g. devRelease / stagingRelease
# or:
cd android && ./gradlew assemble<Flavor>Release && cd ..
adb install -r android/app/build/outputs/apk/<flavor>/release/app-<flavor>-release.apk
```
Release Android builds need a signing config; most RN templates sign release with the debug
keystore. If the build fails on signing, use the debug variant + Metro instead of editing gradle.

Check what is installed first (`rnsmoke analyze` prints version + debug/release per device). An
installed build signed with another key (typically release vs debug) makes `install` fail with
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`. Prefer building the variant with the same signing as the
installed one (e.g. `assemble<Flavor>Release` when a release build is installed); `adb uninstall`
wipes that app's data on the device — ask before doing it. Building only the emulator ABI is much
faster: `./gradlew app:install<Flavor>Release -PreactNativeArchitectures=arm64-v8a` (x86_64 on Intel).
Make sure both platforms run the **same app version** so the two result columns are comparable; if
that is impossible (e.g. the current branch does not build), test what is installed and state both
versions in the report ("Build version" shows them automatically).

Release builds of apps using Sentry / Crashlytics may try to upload source maps during the build — an
outward-facing side effect. For local test builds set `SENTRY_DISABLE_AUTO_UPLOAD=true` (Sentry RN
gradle plugin / Xcode build phase) unless the user wants the upload.

## Build from source — Expo

```bash
npx expo prebuild            # only if the project has no ios/ android/ folders and the user agrees
npx expo run:ios --configuration Release --device "iPhone 15"
npx expo run:android --variant release
# EAS: a profile with "ios": {"simulator": true} produces an installable simulator .app
```
Expo dev-client builds need the dev server (`npx expo start`) and a deep link to the server URL;
prefer a release / preview build for Maestro.

## Debug builds

```bash
rnsmoke -C <project> metro start --prewarm ios,android   # starts Metro in the background + builds bundles
rnsmoke -C <project> metro status
rnsmoke -C <project> metro stop                          # only stops a Metro that rnsmoke started
```
Android debug builds also need `adb reverse tcp:8081 tcp:8081` — `rnsmoke run` does it.

## Common build problems

| Problem | Fix |
|---|---|
| Wrong Node version | use the version in `.nvmrc` / `package.json#engines` (`nvm use`) |
| CocoaPods errors | `cd ios && bundle install && bundle exec pod install --repo-update` |
| Gradle needs Java 17 | `export JAVA_HOME=$(/usr/libexec/java_home -v 17)` |
| Simulator build asks for signing | simulator builds don't need signing; use `-sdk iphonesimulator` |
| Several schemes / flavors | pick the staging/dev one matching the app id in `rnsmoke init`; ask if unsure |

Never change the app's source, native config or env files to get a build working — ask the user.
