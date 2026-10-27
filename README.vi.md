# rn-maestro-smoke

[English](README.md) | **Tiếng Việt**

Skill cho **Claude Code** để chạy **smoke test tự động** cho app **React Native** bằng **Maestro**,
rồi xuất kết quả ra **file Excel** có thêm **1 tab mới đặt tên theo ngày test** (`DDMM`, ví dụ `2710`),
định dạng y hệt sheet test case gốc (`Test ID | Platform | Section | Description | Expected result |
Actual result | Result | IOS | ANDROID | Test data | Note | Tester`).

Bạn chỉ cần đưa cho Claude: **link repo này**, **source code React Native**, và **file test case**
(`.xlsx`, `.csv` export từ Google Sheets, hoặc không có gì — Claude sẽ tự sinh test case từ code).

```
Test case (.xlsx/.csv) ──► Claude đọc case + code app ──► viết Maestro flow cho từng case
        │                                                        │
        └──────── file Excel + tab "DDMM" ◄── kết quả + ảnh evidence ◄── chạy trên Simulator/Emulator
```

---

## 1. Cách dùng nhanh (khuyên dùng)

Mở Claude Code ở bất kỳ đâu và dán prompt (thay đường dẫn cho đúng):

```text
Clone https://github.com/<your-org>/rn-maestro-smoke về ~/tools/rn-maestro-smoke rồi chạy ./install.sh.
Sau đó dùng skill rn-smoke-test để chạy smoke test cho app React Native ở ~/projects/my-app
với file test case "~/Downloads/[App - MyApp] Smoke testing.xlsx" trên iOS simulator.
Tài khoản test: email ... / mật khẩu ... (nếu có).
```

Các biến thể:

| Trường hợp | Prompt |
|---|---|
| File `.csv` export từ Google Sheets | `... với file test case "~/Downloads/[App - MyApp] Smoke testing - app.csv"` |
| Không có test case | `... app ở ~/projects/my-app, chưa có test case, hãy tự tạo bộ smoke test rồi chạy` |
| Cả iOS và Android | `... chạy trên cả iOS simulator và Android emulator` |
| Lần sau (đã cài skill) | `/rn-smoke-test ~/projects/my-app ~/Downloads/smoke.xlsx ios` (cài dạng plugin: `/rn-maestro-smoke:rn-smoke-test ...`) — hoặc chỉ cần nói "chạy smoke test ..." |

Claude sẽ: kiểm tra môi trường → phân tích project → đọc test case → phân loại case nào tự động được
→ khám phá UI thật trên simulator → viết flow Maestro → chạy, tự sửa flow lỗi (không "sửa" để che bug app)
→ xuất Excel → báo cáo PASS/FAIL/PENDING kèm lý do.

## 2. Kết quả nhận được

`<project>/.maestro/smoke/runs/<ngày_giờ>/`

| File | Nội dung |
|---|---|
| `<tên file gốc> - 2710.xlsx` | Toàn bộ workbook gốc (không đụng các tab cũ) + **tab mới `2710`** clone từ tab test case: cùng cột, style, độ rộng, freeze header, dropdown, tô màu |
| `evidence/ios/TC-xxx.png`, `evidence/android/...` | Ảnh màn hình tại thời điểm kiểm tra (link trong cột IOS / ANDROID) |
| `results-ios.json`, `logs/`, `maestro/` | Kết quả chi tiết, log và artifact gốc của Maestro |

Trong tab mới:

| Cột | Giá trị |
|---|---|
| **Result** | `PASS` — flow chạy qua và mọi ý trong *Expected result* đều được kiểm tra · `FAIL` — app không đạt *Expected result* · `PENDING` — chưa kiểm chứng được (lý do ở Note) |
| **Actual result** | `As expected` hoặc mô tả điều app thực sự làm |
| **Note** | `[Auto] Maestro iOS: PASS in 42s`, `[Manual] Needs the confirmation-code email`, `[Blocked] Needs TEST_EMAIL`... |
| **Test ID** | Điền `TC-001...` nếu cột đang trống (để đối chiếu với evidence) |
| Khối summary | Tested by, Test Date, Build version (lấy từ app đã cài), số Pass / Fail / Pending, tổng số case |

> Mặc định link evidence là đường dẫn tương đối — khi gửi cho người khác hãy gửi **cả thư mục run** (hoặc zip lại),
> hoặc upload evidence lên Google Drive (mục dưới).
> Muốn import vào Google Sheets: `rnsmoke export --only-new-tab` rồi *File → Import → Insert new sheet(s)*.
> Cần đúng định dạng `.xls` (Excel 97-2003): `rnsmoke export --xls` (cần LibreOffice).

### Link evidence cho cả team — Google Drive (khuyên dùng)

Ảnh/video evidence được upload lên **Google Drive của người chạy** (`RN smoke evidence/<tên sheet>/<run>`), link
`drive.google.com/file/d/...` được ghi vào từng ô cột IOS / ANDROID (giống sheet cũ).

- **Quyền tối thiểu `drive.file`**: công cụ chỉ thấy file do nó tạo, không đọc được gì khác trong Drive.
- **Mặc định riêng tư**: chỉ bạn + người được share thư mục xem được (share `RN smoke evidence` cho team một lần là xong);
  `--share domain` = cả công ty xem được (chỉ đọc).
- Đăng nhập OAuth do công cụ tự làm (trình duyệt, PKCE); token tự lưu ở `~/.rnsmoke/google-token.json` (quyền 600)
  và tự gia hạn. Gỡ quyền tại myaccount.google.com/permissions.

**Tạo OAuth client — 1 lần cho cả team, ai làm cũng được (~10 phút, không cần quyền admin Workspace)**
1. Tạo project: <https://console.cloud.google.com/projectcreate> (tên tuỳ ý, ví dụ `rnsmoke`).
2. Bật Drive API: <https://console.cloud.google.com/apis/library/drive.googleapis.com> → **Enable**.
3. Màn hình đồng ý: <https://console.cloud.google.com/auth/overview> → *Get started* → App name `rnsmoke`, email hỗ trợ →
   Audience **Internal** (tài khoản Google Workspace công ty) → email liên hệ → *Create*.
   Nếu không có lựa chọn Internal: chọn **External**, rồi ở *Audience* bấm **Publish app** (quyền `drive.file` không cần
   Google duyệt; nếu để chế độ *Testing* thì token tự hết hạn sau 7 ngày).
4. Tạo client: <https://console.cloud.google.com/auth/clients/create> → Application type **Desktop app** → *Create* →
   **Download JSON** (file `client_secret_….json` nằm trong Downloads).

**Dùng**
```bash
R=~/tools/rn-maestro-smoke/skills/rn-smoke-test/bin/rnsmoke
$R drive-login                                           # tự tìm client_secret_*.json trong Downloads → trình duyệt → Allow
$R -C <project> upload --dry-run                         # xem trước file nào sẽ được upload (không gọi mạng)
$R -C <project> export --upload gdrive                   # Excel với link Drive trong cột IOS / ANDROID (riêng tư)
$R -C <project> export --upload gdrive --share domain    # cả công ty mở được link
```
`drive-login` tự tìm client theo thứ tự: `~/.rnsmoke/`, `skills/rn-smoke-test/google-oauth-client.json`,
`resource/client_secret_*.json` trong repo, rồi `~/Downloads/client_secret_*.json`.
Cho cả team khỏi phải chuyền file: lưu client thành `skills/rn-smoke-test/google-oauth-client.json` rồi `git add -f`
vào **repo private** (`.gitignore` chặn file này mặc định; Google không coi client secret của app Desktop là bí mật).
Link được cache trong `runs/<ngày_giờ>/uploads.json` nên export lại không upload trùng; nếu Drive lỗi, ô đó giữ link
cục bộ và file Excel vẫn được tạo.

<details>
<summary>Phương án khác: rclone, host công khai</summary>

- `--upload rclone` (sau `brew install rclone` + `rnsmoke rclone-setup`): cùng cấu trúc thư mục Drive. Client Google dùng
  chung của rclone đang bị ngừng trong năm 2026 (Google tính phí) và có thể lỗi đăng nhập (Google 500) — nên cấu hình rclone
  với client riêng.
- Host công khai miễn phí — **không dùng cho app khách hàng**: `catbox` (vĩnh viễn, upload ẩn danh không xoá được),
  `litterbox --expire 72h` (tự xoá), `imgbb` (cần `IMGBB_API_KEY`), `droplr` (thử nghiệm, SDK cũ chưa kiểm chứng).
</details>

## 3. Yêu cầu máy

| Thành phần | Ghi chú |
|---|---|
| macOS + Xcode + 1 iOS Simulator đã boot | cho iOS (`open -a Simulator`) |
| Android SDK + emulator | cho Android (`emulator -avd <tên>`) |
| Java 17+ | Maestro cần (`brew install openjdk@17`) |
| [Maestro CLI](https://maestro.mobile.dev) | `curl -fsSL "https://get.maestro.mobile.dev" \| bash` — Claude tự cài nếu thiếu |
| Python 3.9+ | wrapper tự tạo venv và cài `openpyxl` ở `~/.rnsmoke/venv` |
| Node + dependencies của app | chỉ khi cần build app hoặc chạy Metro cho bản debug |

Kiểm tra nhanh: `skills/rn-smoke-test/bin/rnsmoke doctor`

## 4. Cài đặt

**Cách A — script (khuyên dùng):**
```bash
git clone https://github.com/<your-org>/rn-maestro-smoke ~/tools/rn-maestro-smoke
~/tools/rn-maestro-smoke/install.sh          # symlink skill vào ~/.claude/skills/rn-smoke-test
```
`git pull` là cập nhật xong (vì là symlink). `--copy` để copy thay vì symlink, `--project <path>` để cài
riêng cho một project.

**Cách B — plugin marketplace của Claude Code:**
```text
/plugin marketplace add <your-org>/rn-maestro-smoke
/plugin install rn-maestro-smoke@rn-maestro-smoke
```

**Cách C — không cài:** mở Claude Code ngay trong thư mục repo này (file `CLAUDE.md` sẽ hướng dẫn Claude).

## 5. Dữ liệu test & bảo mật

- Tài khoản/dữ liệu test để trong `<project>/.maestro/smoke/.env` (mẫu: `.env.example`), flow dùng `${TEST_EMAIL}`.
  File này đã được git-ignore; flow không bao giờ chứa mật khẩu.
- Case cần trạng thái dữ liệu riêng (user có 2 profile, đã book lớp, có gói tập...) → Claude sẽ liệt kê
  và hỏi **một lần**; không có thì case đó là `PENDING [Blocked]`.
- Claude **không sửa source code app**, không làm thao tác không thể hoàn tác (thanh toán thật, xoá tài khoản,
  tạo dữ liệu trên production) khi chưa được bạn đồng ý rõ ràng. Nên test trên bản dev/staging.

## 6. Thư mục trong project React Native

```
<project>/.maestro/smoke/
  config.json        app id cho iOS/Android, cổng Metro
  manifest.json      mỗi test case → flow / manual / blocked (+ lý do)
  cases.json         test case đã parse lần gần nhất
  flows/<section>/   1 flow Maestro cho mỗi case          ← nên commit
  subflows/          launch sạch, login, ẩn bàn phím...   ← nên commit
  .env               dữ liệu test (git-ignored)
  runs/              kết quả từng lần chạy (git-ignored)
```
Sprint sau: đưa file test case mới, flow cũ được dùng lại (case sửa nhẹ tự relink), Claude chỉ viết flow
cho case mới.

## 7. Lệnh CLI (Claude tự dùng, bạn cũng có thể chạy tay)

```bash
R=~/tools/rn-maestro-smoke/skills/rn-smoke-test/bin/rnsmoke
$R doctor                                         # kiểm tra môi trường
$R device-setup --platform ios                    # tắt "Suggest Strong Passwords" trên simulator (1 lần)
$R -C <project> analyze                           # app id, scheme/flavor, app đã cài (debug/release)
$R -C <project> init                              # tạo .maestro/smoke
$R -C <project> cases --input <file.xlsx|.csv>    # đọc test case
$R -C <project> status                            # độ phủ automation theo section
$R -C <project> mark TC-004 --flow flows/registration/x.yaml
$R -C <project> mark TC-001 --manual "Cần email OTP"
$R -C <project> inspect --platform ios            # liệt kê phần tử trên màn hình + screenshot
$R -C <project> metro start --prewarm ios         # cho bản debug
$R -C <project> run --platform ios                # chạy (batch 10 flow, tự retry flow lỗi)
$R -C <project> results                           # tóm tắt fail/error kèm evidence
$R -C <project> export                            # xuất Excel với tab DDMM
$R -C <project> upload --dry-run                  # xem trước evidence nào sẽ được upload
$R drive-login                                    # 1 lần: đăng nhập Google Drive (OAuth client của team)
$R -C <project> export --upload gdrive            # xuất Excel với link evidence trên Google Drive
```

## 8. Giới hạn cần biết

- Không tự kiểm chứng được: nội dung email/SMS/OTP, push notification, thanh toán thật, dữ liệu ở hệ
  thống bên ngoài (CRM, back-office), camera/biometric → `PENDING [Manual]`.
- Bản **Release** cho kết quả ổn định nhất; bản Debug cần Metro và có overlay LogBox (skill đã xử lý).
- Mỗi flow mất ~0.5–2 phút; lần đầu viết flow cho bộ 100+ case sẽ mất nhiều thời gian nhất, các lần sau
  chỉ chạy lại.

## 9. Phát triển

```bash
python3 -m unittest discover -s tests -v     # 100% offline, không cần thiết bị
```
Cấu trúc:
```
.claude-plugin/            plugin.json + marketplace.json
skills/rn-smoke-test/
  SKILL.md                 quy trình Claude làm theo
  reference/               cheatsheet Maestro cho RN, cách viết flow, phân loại case, build app, xử lý lỗi
  templates/               subflow mẫu, flow ví dụ, setup thiết bị
  bin/rnsmoke              wrapper (tự bootstrap Python env)
  scripts/rnsmoke/         Python package: parse sheet, chạy Maestro, xuất Excel
tests/                     unit test với dữ liệu giả lập
examples/                  checklist mẫu (dữ liệu giả)
install.sh
```
