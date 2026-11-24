# Bản demo `/guest` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/guest` mở một họ `demo` công khai toàn dữ liệu giả, để cho người ngoài xem đúng phần khách thật được xem, không chạm dữ liệu thật.

**Architecture:** Một họ (tree) slug `demo` trong database hiện tại, do script `scripts/seed_demo.py` tạo/đặt lại (logic ở `app/core/demo.py`, script chỉ gọi). Khách vào qua route web `/guest` đặt cookie `tree_slug=demo` (cơ chế `/t/<slug>` có sẵn). Một dải báo "bản demo" hiện khi họ đang xem là `demo`.

**Tech Stack:** FastAPI + SQLAlchemy async + Postgres + pytest (`genealogy-api`); Next.js 15 + vitest (`genealogy-web`).

**Spec:** `genealogy-api/docs/superpowers/specs/2026-11-24-guest-demo-design.md`

## Global Constraints

- Slug họ demo cố định là `demo`; tên cố định `Họ Demo (dữ liệu giả)`. Script **không nhận tham số slug** và chỉ chạm họ có slug `demo`.
- Dữ liệu giả: khoảng 100 người huyết thống, đúng 6 đời, không ảnh, không số điện thoại, không email; hạt giống cố định `20261124` (chạy lại ra đúng bản cũ).
- Phạm vi: chỉ phần khách thật xem được (cây, hồ sơ, tìm kiếm, quan hệ, thống kê, chi phái, sử ký đã đăng, dòng thời gian, bài đệm, lịch giỗ/sự kiện). Không địa điểm, ảnh, quản trị, tài khoản.
- Test API chạy trên Postgres thật (`docker compose up -d --wait db-test`, rồi `uv run pytest`). **Không bao giờ chạy script seed hay test trỏ vào database thật** (container `genealogy-db-1`, `.env`): kiểm tra tay chỉ dùng `DATABASE_URL` tới `genealogy_test` ở cổng 55432.
- Mọi commit kết thúc bằng dòng `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Chưa push.
- Repo: tác vụ 1–3 commit trong `genealogy-api`, 4–5 trong `genealogy-web`, 6 ở repo gốc `gia_pha` (kèm bump hai submodule).

## Review Focus

1. Lỗi giữa chừng khi đặt lại: demo cũ phải còn nguyên, không để lại họ demo nửa vời → test ở Task 2 (`test_failed_reset_keeps_the_previous_demo`).
2. Họ có slug `demo` nhưng là họ thật (có tài khoản, hoặc tên khác `DEMO_NAME`): từ chối, không xoá → Task 2.
3. Dữ liệu giả sai logic (chết trước sinh, cha trẻ hơn con, tuổi cha–con lệch) làm demo trông vô lý và trang kiểm tra dữ liệu báo lỗi → Task 1 (`test_generated_data_has_no_data_health_warnings`).
4. Khách đọc nhầm phần không thuộc phạm vi (địa điểm, bài nháp) → Task 2 (`/places` 401, danh sách bài chỉ có bài đã đăng).
5. Họ demo không có quản trị viên làm trang superadmin báo "họ không có quản trị viên" → Task 3.

---

### Task 1: Bộ sinh dữ liệu giả (thuần, không database)

**Files:**
- Create: `app/core/demo.py` (phần dữ liệu)
- Test: `tests/test_demo_data.py`

**Interfaces:**
- Produces (dùng trong Task 2):
  - `DEMO_SLUG = "demo"`, `DEMO_NAME = "Họ Demo (dữ liệu giả)"`, `DEMO_SEED = 20261124`.
  - dataclass `DemoPerson(key: int, name: str, gender: str, generation: int, parent_key: int | None, partner_key: int | None, birth_year: int, death_year: int | None, death_month: int | None, death_day: int | None, birth_month: int | None, birth_day: int | None, hometown: str | None, marriage_year: int | None)`. `gender` là `"male"`/`"female"`. Người huyết thống có `partner_key=None`; vợ/chồng có `parent_key=None` và `partner_key` = key của người huyết thống. Danh sách luôn xếp cha trước con.
  - dataclass `DemoArticle(title: str, kind: str, body: str, status: str, pinned: bool)`; `DemoTimeline(year: int, month: int | None, day: int | None, title: str, body: str | None)`; `DemoWord(generation: int, word: str, meaning: str | None)`; `DemoEvent(title: str, description: str | None, kind: str, calendar: str, month: int, day: int, repeats_yearly: bool)`; `DemoBranch(head_key: int, name: str, color: str)`.
  - dataclass `DemoFamily(people, branches, articles, timeline, poem, events)` (mỗi trường là list của dataclass tương ứng).
  - `build_demo_family(seed: int = DEMO_SEED) -> DemoFamily`.

- [ ] **Step 1: Viết test thất bại** trong `tests/test_demo_data.py` (hàm sinh là thuần, nhưng `tests/conftest.py` dựng lại database test cho mọi file test nên vẫn cần `db-test` đang chạy và không được chạy song song với pytest khác):
  - `test_build_is_deterministic`: hai lần gọi cùng seed cho `==` (dataclass so sánh được); seed khác cho tên khác.
  - `test_shape_matches_the_spec`: người huyết thống (`partner_key is None`) có 90 ≤ số ≤ 130 và `max(generation) == 6`; có đúng 1 gốc (`parent_key is None` trong nhóm huyết thống); 3 chi phái, mỗi chi có `head_key` thuộc đời 2; 4 bài sử ký trong đó đúng 1 `status == "draft"` và có một bài `kind == "precepts"`; `len(poem) == 6`; ít nhất 5 mục dòng thời gian; ít nhất 3 sự kiện, mọi sự kiện `repeats_yearly` (không để sự kiện một lần sẽ hết hạn).
  - `test_nothing_personal`: mọi `DemoPerson` không có trường điện thoại/email (dataclass không có), và `hometown` chỉ nằm trong danh sách địa danh cố định của module.
  - `test_ages_are_plausible`: với mọi con: tuổi cha lúc sinh con trong khoảng 18–45; `death_year > birth_year` và tuổi thọ ≤ 95 khi có `death_year`; người đời 5–6 còn sống (`death_year is None`), người đời 1–4 đã mất và có `death_month`/`death_day` (để có giỗ).
  - `test_spouses_are_opposite_gender_and_same_generation`: mỗi vợ/chồng khác giới với người huyết thống tương ứng, cùng `generation`, `marriage_year` không sớm hơn năm sinh của cả hai cộng 16.
  - `test_keys_are_unique_and_parents_come_first`.
- [ ] **Step 2: Chạy, thấy FAIL** — `uv run pytest tests/test_demo_data.py -q` → lỗi import `app.core.demo`.
- [ ] **Step 3: Cài đặt `build_demo_family`** trong `app/core/demo.py`. Dùng `random.Random(seed)` cho mọi lựa chọn (không dùng `random` toàn cục, không `datetime.now`). Họ giả "Lê" (đệm/tên chọn từ danh sách tên Việt phổ biến cố định trong module, vợ mang họ khác); đời 1 sinh quanh 1850, mỗi đời cách khoảng 25–30 năm; số con mỗi người chọn từ 1–4 sao cho tổng huyết thống rơi vào 90–130 và đúng 6 đời (chỉnh tham số, không chỉnh test); ba người con trai trưởng ở đời 2 là `head_key` của ba chi (tên chi, màu hex 7 ký tự). Bài sử ký: nguồn gốc, tộc ước (`precepts`, ghim), một sự kiện dòng họ, và một **bản nháp** tên "Bản nháp chưa đăng". Bài đệm 6 từ cho 6 đời. Sự kiện: giỗ Tổ âm lịch (`memorial`, lunar, lặp hằng năm), họp mặt đầu năm (`gathering`, solar, lặp hằng năm), thêm một sự kiện nữa theo âm lịch. Nội dung chữ giả, ngắn.
- [ ] **Step 4: Chạy test, thấy PASS** — `uv run pytest tests/test_demo_data.py -q`.
- [ ] **Step 5: Commit** — `git add app/core/demo.py tests/test_demo_data.py && git commit -m "feat(api): deterministic fake family generator for the guest demo"`.

---

### Task 2: Tạo/đặt lại họ demo trong database, an toàn

**Files:**
- Modify: `app/core/demo.py` (thêm phần database)
- Test: `tests/test_demo_seed.py`

**Interfaces:**
- Consumes (Task 1): `DemoFamily`, `DemoPerson`, `build_demo_family`, `DEMO_SLUG`, `DEMO_NAME`.
- Consumes (có sẵn): `app.core.tree_removal.delete_tree_data(db, tree) -> Removal`, `app.core.tenants.get_tree_by_slug`, models `Tree, Member, Marriage, Branch, Article, TimelineEntry, GenerationWord, Event, SiteSetting, User`, `app.routers.articles.make_slug(title) -> str` (import trong hàm để tránh vòng).
- Produces (dùng trong Task 3):
  - `class DemoGuardError(RuntimeError)`.
  - dataclass `DemoSummary(tree_id: int, members: int, spouses: int, articles: int)`.
  - `async def reset_demo(db: AsyncSession, family: DemoFamily | None = None) -> DemoSummary`: nếu có họ slug `demo` thì kiểm tra rồi xoá dữ liệu của chính họ đó, rồi tạo lại và nạp `family` (mặc định `build_demo_family()`); **toàn bộ trong một giao dịch**, commit một lần ở cuối; lỗi giữa chừng thì `rollback()` rồi ném lại lỗi. Tạo họ bằng `Tree(...)` trực tiếp (không dùng `create_tree` vì nó tự commit). Đặt `SiteSetting(tree_id, "visibility", "public")`. Bài đã đăng có `status="published"`; slug bài từ `make_slug`, thêm `-2`, `-3` khi trùng.
  - Điều kiện từ chối (`DemoGuardError`, không xoá gì): họ `demo` đã có mà (a) có bất kỳ `User` nào thuộc họ đó, hoặc (b) `name != DEMO_NAME`.

- [ ] **Step 1: Viết test thất bại** trong `tests/test_demo_seed.py` (dùng fixture `session`, `make_client`; mỗi test tự tạo họ cần dùng):
  - `test_reset_creates_a_public_demo_tree`: sau `reset_demo(session)`: có đúng 1 họ slug `demo`, tên `DEMO_NAME`, `status == "active"`, `get_tree_settings(...)["visibility"] == "public"`; `summary.members` khớp số `Member` huyết thống của họ.
  - `test_reset_twice_gives_the_same_data`: chạy hai lần → cùng số người, cùng danh sách tên theo thứ tự `id`, và **chỉ một** họ `demo`.
  - `test_guest_reads_only_the_in_scope_parts` (khách = `make_client()` với `guest.cookies.set("tree_slug", "demo")`): `/site/info` → `visibility == "public"`, `tree_slug == "demo"`; `/members/tree` → 200 có gốc; `/members/search?q=` bằng họ giả → 200 và có kết quả; `/stats/overview` 200; `/branches` có 3; `/timeline` ≥ 5; `/generation-poem` có 6; `/calendar/upcoming` 200; `/articles` trả đúng số bài đã đăng (3) và **không** có "Bản nháp chưa đăng"; `/places` → 401.
  - `test_other_tree_is_untouched`: trước khi seed tạo họ "Họ thật" slug `ho-that` với vài `Member` (có `avatar_url`), một `Marriage`, một `User` admin (qua `create_user`), một `Article`, một `Event`, `visibility=private`. Chụp ảnh trạng thái (đếm từng bảng theo `tree_id`, danh sách tên người, giá trị setting, `User.email`). Chạy `reset_demo` **hai lần**; ảnh trạng thái giống hệt, và các file avatar giả (tạo trong `upload_dir`) vẫn còn.
  - `test_failed_reset_keeps_the_previous_demo`: seed một lần, ghi lại `tree_id` và số người; gọi `reset_demo(session, family)` với `family` đã làm hỏng (`dataclasses.replace`, thêm một `DemoPerson` có `parent_key=999999`) trong `pytest.raises(Exception)`; sau đó họ `demo` vẫn có đúng `tree_id` cũ và đúng số người cũ.
  - `test_refuses_a_demo_slug_that_has_accounts`: tạo họ slug `demo` tên `DEMO_NAME` kèm một admin → `reset_demo` ném `DemoGuardError`; họ, admin và người của họ còn nguyên.
  - `test_refuses_a_demo_slug_with_another_name`: họ slug `demo` tên "Họ khác", không có tài khoản → `DemoGuardError`, họ còn nguyên.
  - `test_generated_data_has_no_data_health_warnings`: sau seed, `check_layout(await load_layout(session, tree_id))` (`app.core.data_health`, `app.core.tree_layout`) không có `Finding` nào có `severity == "warning"`.
- [ ] **Step 2: Chạy, thấy FAIL** — `uv run pytest tests/test_demo_seed.py -q` (cần `docker compose up -d --wait db-test`).
- [ ] **Step 3: Cài đặt `reset_demo`, `DemoGuardError`, `DemoSummary`** trong `app/core/demo.py`. Chèn người theo thứ tự (cha trước con) bằng `flush()` để lấy `id`; vợ/chồng là `Member` có `parent_id=None` kèm `Marriage(member_id, spouse_id, marriage_year)`; `birth_order` để trống; `Branch.root_member_id` từ `head_key`; `death_is_lunar` giữ mặc định.
- [ ] **Step 4: Chạy test, thấy PASS** — `uv run pytest tests/test_demo_seed.py tests/test_demo_data.py -q`.
- [ ] **Step 5: Commit** — `git add app/core/demo.py tests/test_demo_seed.py && git commit -m "feat(api): reset_demo creates/replaces only the 'demo' tree, atomically, with guards"`.

---

### Task 3: Script `seed_demo.py` và bỏ họ demo khỏi mục "họ không có quản trị viên"

**Files:**
- Create: `scripts/seed_demo.py`
- Modify: `app/core/platform_overview.py` (truy vấn `without_admin`, dòng 34)
- Test: `tests/test_demo_seed.py` (thêm)

**Interfaces:**
- Consumes (Task 2): `reset_demo`, `DemoGuardError`, `DemoSummary`, `DEMO_SLUG`.
- Produces: lệnh `python scripts/seed_demo.py` (không tham số).

- [ ] **Step 1: Viết test thất bại** (thêm vào `tests/test_demo_seed.py`): `test_demo_tree_is_not_a_tree_without_admin`: chỉ có họ demo (sau `reset_demo`) → `compute_platform_overview(session)` không có item `key == "trees_without_admin"`; thêm họ `ho-that` không admin → item đó có `count == 1`.
- [ ] **Step 2: Chạy, thấy FAIL** — `uv run pytest tests/test_demo_seed.py::test_demo_tree_is_not_a_tree_without_admin -q` (count = 2 hoặc 1 sai).
- [ ] **Step 3: Sửa `compute_platform_overview`**: điều kiện đếm họ không có admin thêm `Tree.slug != DEMO_SLUG`. Số họ tổng (`trees`) giữ nguyên (demo vẫn tính, đã ghi trong spec).
- [ ] **Step 4: Viết `scripts/seed_demo.py`**: theo khuôn `scripts/seed_members.py` (thêm `os.getcwd()` vào `sys.path`, `asyncio.run`); **không có đối số**; in một dòng `Đích: <host>:<port>/<db>` lấy từ `get_settings().database_url` (ẩn mật khẩu) **trước** khi làm gì; gọi `reset_demo` và in tóm tắt (`Đã đặt lại họ 'demo': N người, M vợ/chồng, K bài`); `DemoGuardError` thì in thông báo và thoát mã 1.
- [ ] **Step 5: Chạy test, thấy PASS** — `uv run pytest tests/test_demo_seed.py -q`.
- [ ] **Step 6: Kiểm tra tay trên database thử** (không phải database thật): `export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/genealogy_test` rồi chạy `uv run python scripts/seed_demo.py` hai lần. Mong đợi: dòng `Đích:` ghi `127.0.0.1:55432/genealogy_test`, cả hai lần cùng số người, lần hai không báo lỗi.
- [ ] **Step 7: Chạy cả bộ API** — `uv run pytest -q` → toàn bộ xanh (682 cũ + test mới). Commit: `git add scripts/seed_demo.py app/core/platform_overview.py tests/test_demo_seed.py && git commit -m "feat(api): seed_demo script; the demo tree is not 'a family without an admin'"`.

---

### Task 4: Route web `/guest`

**Files:**
- Create: `src/app/guest/route.ts`, `src/app/guest/route.test.ts`
- Modify: `src/lib/auth/tree.ts`, `src/lib/auth/tree.test.ts`, `src/app/t/[slug]/route.ts`, `vitest.config.ts`

**Interfaces:**
- Produces (Task 5 dùng):
  - trong `src/lib/auth/tree.ts`: `export const DEMO_TREE_SLUG = 'demo'`; `export function isDemoTree(slug: string | null | undefined): boolean`; `export function treeSlugSetCookie(slug: string): string` trả đúng chuỗi `tree_slug=<slug>; Path=/; Max-Age=31536000; SameSite=Lax`.
  - `export async function GET(): Promise<Response>` trong `src/app/guest/route.ts`.

- [ ] **Step 1: Viết test thất bại**:
  - `tree.test.ts`: `isDemoTree('demo') === true`; `false` cho `'phu-oc'`, `'Demo'`, `'demo-2'`, `''`, `null`, `undefined`; `treeSlugSetCookie('demo') === 'tree_slug=demo; Path=/; Max-Age=31536000; SameSite=Lax'`.
  - `route.test.ts`: `const res = await GET()` → `res.status === 307`, `res.headers.get('location') === '/'`, `res.headers.get('set-cookie') === 'tree_slug=demo; Path=/; Max-Age=31536000; SameSite=Lax'`.
- [ ] **Step 2: Chạy, thấy FAIL** — `npx vitest run src/lib/auth/tree.test.ts src/app/guest` (thiếu hàm/route).
- [ ] **Step 3: Cài đặt** `DEMO_TREE_SLUG`, `isDemoTree`, `treeSlugSetCookie` trong `tree.ts`; viết `guest/route.ts` (Location tương đối `'/'` như `/t/[slug]`, comment lý do giống route đó); đổi `t/[slug]/route.ts` dùng `treeSlugSetCookie` (hành vi không đổi). `vitest.config.ts` thêm `resolve.alias` `'@'` → `./src` (route dùng import `@/...`; `tsconfig` đã có paths tương ứng).
- [ ] **Step 4: Chạy test, thấy PASS** — `npx vitest run` (toàn bộ, 426 cũ + mới) và `npx tsc --noEmit`, `npm run lint`.
- [ ] **Step 5: Commit** — `git add src vitest.config.ts && git commit -m "feat(web): /guest route sets the demo family cookie"`.

---

### Task 5: Dải báo "Bản demo"

**Files:**
- Create: `src/components/layout/DemoBanner.tsx`, `src/components/layout/DemoBanner.test.ts`
- Modify: `src/components/layout/useFamilyName.ts`, `src/components/layout/AppShell.tsx`

**Interfaces:**
- Consumes (Task 4): `isDemoTree(slug)`.
- Produces: `export function DemoBanner({ slug }: { slug: string | null }): JSX.Element | null` (trả `null` khi không phải demo); trong `useFamilyName.ts`: `export function useFamilySite(user: CurrentUser | null): { familyName: string | null; treeSlug: string | null }` (`treeSlug` lấy từ cùng lần gọi `/api/site/info` hiện có, field `tree_slug`; chỉ có giá trị cho khách; `useFamilyName` giữ lại nếu nơi khác còn dùng, nếu không thì bỏ).

- [ ] **Step 1: Viết test thất bại** `DemoBanner.test.ts` (file `.ts`, không JSX, dùng `renderToStaticMarkup(createElement(DemoBanner, { slug }))` từ `react-dom/server`): slug `'demo'` → chuỗi chứa `Bản demo` và `dữ liệu giả`; slug `'phu-oc'`, `null` → chuỗi rỗng.
- [ ] **Step 2: Chạy, thấy FAIL** — `npx vitest run src/components/layout/DemoBanner.test.ts`.
- [ ] **Step 3: Cài đặt** `DemoBanner` (một dải cao một dòng, màu nổi bật nhưng không chói, chữ: "Bản demo — toàn bộ dữ liệu trên trang này là giả"), `useFamilySite`, và đặt `DemoBanner` ở đầu cột bên phải của `AppShell` (trên `Header`). Nếu vitest không đọc được JSX của `.tsx` (tsconfig `jsx: preserve`), thêm `esbuild: { jsx: 'automatic' }` vào `vitest.config.ts`.
- [ ] **Step 4: Chạy** — `npx vitest run`, `npx tsc --noEmit`, `npm run lint` đều xanh.
- [ ] **Step 5: Kiểm tra tay** (stack dev, không phải dữ liệu thật): seed demo vào database thử như Task 3, chạy web trỏ vào API dùng database đó, mở `/guest` trong cửa sổ ẩn danh. Mong đợi: thấy cây giả, dải "Bản demo" hiện; mở `/t/<slug họ khác>` thì dải biến mất.
- [ ] **Step 6: Commit** — `git add src vitest.config.ts && git commit -m "feat(web): demo banner for guests of the demo family"`.

---

### Task 6: Tài liệu và bump

**Files:**
- Modify: `DOCKER.md` (repo gốc, thêm mục sau "Triển khai lên server"), `genealogy-api/docs/superpowers/specs/2026-11-24-guest-demo-design.md` (dòng trạng thái)

- [ ] **Step 1: Viết mục "Bản demo cho khách (`/guest`)" trong `DOCKER.md`**: tạo/đặt lại bằng `docker compose exec api python scripts/seed_demo.py` (chạy lại = đặt lại về đúng bản cũ); `/guest` là link đưa cho người xem; ba hệ quả của cách A (họ demo nằm trong sao lưu và danh sách/số liệu của superadmin; từ hai họ trở lên khách vào bằng `/t/<slug>`, nên nếu họ thật bật công khai thì phát link có slug; người đang đăng nhập mở `/guest` vẫn thấy họ của mình, dùng cửa sổ ẩn danh); cách gỡ demo (superadmin tạm ngưng rồi xoá họ `demo` ở `/he-thong`); script từ chối khi họ `demo` có tài khoản hoặc tên khác.
- [ ] **Step 2: Đổi dòng trạng thái của spec** thành "Đã duyệt 2026-11-24, đã có kế hoạch".
- [ ] **Step 3: Commit và bump** — commit spec/plan trong `genealogy-api` (`docs: guest demo spec approved + plan`); ở repo gốc `git add DOCKER.md genealogy-api genealogy-web && git commit -m "feat: guest demo (/guest, fake 'demo' family) + docs; bump submodules"`. Kiểm tra: `git status` sạch ở cả ba repo; `git submodule status` không có dấu `+`.
