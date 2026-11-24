# Bản demo cho khách: `/guest` với dữ liệu giả

Ngày 2026-11-24. Trạng thái: đã duyệt 2026-11-24, đã có kế hoạch (`../plans/2026-11-24-guest-demo.md`).

## Mục đích

Có một đường dẫn công khai `/guest` để cho người ngoài xem sản phẩm bằng **dữ liệu giả**, mà không đưa dữ liệu thật của
các dòng họ ra trước mặt họ và không để demo ảnh hưởng tới dữ liệu thật.

## Phạm vi

- **Có:** đúng những gì một khách thật của họ công khai được xem: cây, hồ sơ (bản đã ẩn bớt), tìm kiếm, quan hệ, thống kê,
  chi phái, sử ký (bài đã đăng), dòng thời gian, bài đệm, lịch giỗ và sự kiện.
- **Không có (không làm):** ảnh/tài liệu, địa điểm, nhập liệu, quản trị, đăng nhập vào demo. Khách thật cũng không thấy các phần này.
- **Điều không được xảy ra:** demo ghi, sửa hoặc xoá bất cứ dòng nào của họ thật; script seed nhận slug từ bên ngoài.

## Các cách đã cân nhắc

- **A. Họ `demo` trong database hiện tại (đã chọn).** Ít code nhất, giao diện và API thật, lịch âm và tìm kiếm thật.
  Đánh đổi: chung database (lẫn vào sao lưu, số liệu nền tảng, danh sách superadmin); thêm họ thứ hai làm mất quy tắc "chỉ có một
  họ thì khách không cần link `/t/<slug>`"; người đang đăng nhập sẽ thấy họ của mình thay vì demo.
- **B. Bộ chạy riêng (compose thứ hai, subdomain).** Tách hoàn toàn nhưng thêm container, cổng, DNS, TLS và một lần `update.sh`. Đã đề xuất, bạn chọn A.
- **C. Demo ở trình duyệt, không database.** Phải viết lại khoảng 15 endpoint (kể cả lịch âm) và giữ khớp API thật. Loại.

## Thiết kế

1. **Script `scripts/seed_demo.py`** (API). Tạo họ có slug **`demo`** (cố định trong code, không nhận tham số slug) tên "Họ Demo (dữ liệu giả)",
   đặt `visibility=public`, rồi sinh dữ liệu giả có hạt giống cố định (chạy lại ra đúng bản cũ): khoảng 100 người, 6 đời, vợ/chồng,
   vài chi phái, vài bài sử ký đã đăng (một bài tộc ước, một bài nguồn gốc), dòng thời gian, bài đệm, vài sự kiện và ngày giỗ.
   Tên người là tên Việt phổ biến ghép ngẫu nhiên, không lấy từ dữ liệu thật; không có ảnh, không có số điện thoại hay email.
2. **Chạy lại = đặt lại demo.** Nếu họ `demo` đã có, script xoá dữ liệu của *chính họ đó* bằng `delete_tree_data` rồi tạo lại.
   Không có đường nào để script chạm tới họ khác: nó chỉ tìm họ theo slug `demo` và dừng nếu slug đó trỏ vào họ có tài khoản đăng nhập thật.
   Chạy trên server: `docker compose exec api python scripts/seed_demo.py`.
3. **Route web `/guest`** (`src/app/guest/route.ts`), cùng kiểu với `/t/[slug]`: đặt cookie `tree_slug=demo`, chuyển về `/`.
4. **Dải báo "Bản demo, dữ liệu giả"** ở đầu trang khi họ đang xem có slug `demo` (`/site/info` đã trả `tree_slug`, không cần đổi API).
5. **Tài liệu:** mục trong DOCKER.md nói cách seed/reset demo, và ba hệ quả của cách A (xem dưới).

## Hệ quả của cách A (ghi vào tài liệu)

- Họ `demo` nằm trong sao lưu và trong số liệu/danh sách của superadmin. Nó tên rõ là demo nên dễ nhận ra.
- Khi có từ hai họ, khách phải vào bằng link `/t/<slug>` (họ thật hiện đang riêng tư nên chưa ảnh hưởng gì; nếu sau này bật công khai thì phát link có `/t/phu-oc`).
- Người đang đăng nhập bằng tài khoản thật mở `/guest` vẫn thấy họ của mình (đăng nhập thắng cookie). Muốn xem demo thì dùng cửa sổ ẩn danh hoặc đăng xuất.

## Kiểm thử

Test API trên Postgres thật: seed tạo đúng họ `demo` công khai; khách đọc được cây, tìm kiếm, thống kê, sử ký, lịch; chạy lại hai lần ra cùng số người;
**dữ liệu của một họ khác (tạo sẵn trong test) không đổi một dòng nào** sau seed và sau reset; seed từ chối khi slug `demo` thuộc họ có tài khoản thật.
Test web: route `/guest` đặt đúng cookie; dải demo chỉ hiện khi slug là `demo`.

## Để người xây quyết

- Họ `demo` không có quản trị viên nên trang superadmin sẽ báo "1 họ không có quản trị viên". Cách xử lý (bỏ qua họ demo trong mục đó, hoặc
  tạo một tài khoản admin với mật khẩu ngẫu nhiên không ai biết) do người xây chọn; tôi nghiêng về bỏ qua họ `demo` trong mục đó.
- Số lượng và nội dung cụ thể của dữ liệu giả.
