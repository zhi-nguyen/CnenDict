# ĐẶC TẢ KIẾN TRÚC VÀ CẤU TRÚC ĐỀ THI HSK (EXAMS SPECIFICATION)

Tài liệu này mô tả chi tiết kiến trúc phần mềm, tính năng tối thiểu, cấu trúc dữ liệu đề thi các cấp độ HSK (HSK 1, 3, 4, 6, 7-9) và các nguyên tắc thiết kế giao diện đa ngôn ngữ (tiếng Anh & tiếng Trung), đảm bảo hiển thị tối ưu trên thiết bị di động (Mobile) và máy tính (PC).

---

## 1. Kiến Trúc Hệ Thống (System Architecture)

Hệ thống thi cử được chia làm 3 lớp chính theo triết lý **Separation of Concerns (SoC)**: Lớp dữ liệu (Database Models), Lớp cổng API (Gateway API) và Lớp giao diện người dùng (Frontend Client).

```mermaid
graph TD
    subgraph Backend (Django)
        Exam[Exam Model] -->|1:N| Section[Section Model]
        Section -->|1:N| Question[Question Model]
        Question -->|1:N| Option[Option Model]
        Signal[Post-Save/Delete Signals] -->|Evicts| Cache[Redis Cache]
    end

    subgraph API Gateway
        Route[/api/core/exams/::id/] --> Cache
    end

    subgraph Frontend (Next.js Client)
        Page[exam/take/:examId/page.tsx] -->|Fetch details| Route
        State[React States: answers, timeRemaining, isSubmitted]
        Storage[(Local Storage: examState)] <-->|Save/Resume| State
        Settings[Settings Store: Volume, Speed] -->|Control| Audio[HTML5 Audio Players]
        Gamification[Gamification Store] -->|Sync XP/Streak| State
    end
```

### 1.1. Backend Database Models (Django)
Định nghĩa trong [models.py](file:///f:/BaiTap_DuAn/XiaoYue/XiaoYueDict/core_django/apps/exams/models.py):

*   **`Exam`**: Lưu trữ thông tin tổng quan của đề thi (metadata) và cấu hình phòng thi (settings).
    *   *Trường dữ liệu*: `exam_id` (CharField, unique), `exam_name`, `exam_version`, `level` (phân loại từ HSK 1 - HSK 9), `total_questions`, `total_time_minutes`, `total_score`, `passing_score`, `language` ('en'/'zh').
    *   *Settings*: `allow_resume` (cho phép làm tiếp), `max_attempts` (số lượt làm tối đa), `shuffle_questions` (trộn câu hỏi), `shuffle_options` (trộn đáp án), `show_explanation_after` (thời điểm hiện giải thích).
    *   *Cache Eviction*: Sử dụng Django signals `post_save` và `post_delete` để tự động dọn dẹp cache của đề thi (`clear_exam_cache`) khi có cập nhật từ trang quản trị.
*   **`Section`**: Đại diện cho các phần thi kỹ năng (Listening, Reading, Writing, Translation, Speaking).
    *   *Trường dữ liệu*: `exam` (ForeignKey), `section_id`, `section_name` (Listening/Reading/Writing), `part_number` (phần 1, 2, 3...), `instruction` (hướng dẫn làm bài), `section_audio_url` (file nghe chung của phần), `ordering`.
*   **`Question`**: Lưu thông tin câu hỏi chi tiết.
    *   *Trường dữ liệu*: `section` (ForeignKey), `question_id`, `question_type` (true_false, multiple_choice, fill_blank, matching, ordering, essay), `difficulty` (easy, medium, hard), `points`, `tags` (JSONField: nhãn ngữ pháp, từ vựng...), `audio_url` (audio riêng), `audio_start_time`/`audio_end_time` (mốc thời gian trích xuất từ audio chung), `audio_script` (nội dung bài nghe), `question_text` (văn bản câu hỏi), `image_url` (hình ảnh đề bài), `correct_answer`, `explanation` (giải thích đáp án).
*   **`Option`**: Lưu các lựa chọn đáp án cho câu hỏi trắc nghiệm/đúng sai.
    *   *Trường dữ liệu*: `question` (ForeignKey), `option_id` (opt_A, opt_B, opt_True...), `text` (nội dung chữ), `image_url` (hình ảnh đáp án), `image_description`.

### 1.2. Frontend Client States (Next.js)
Định nghĩa trong [page.tsx](file:///f:/BaiTap_DuAn/XiaoYue/XiaoYueDict/frontend_nextjs/src/app/[lang]/exam/take/[examId]/page.tsx):

*   **Khởi tạo đa ngôn ngữ (`language`)**: Nhận diện thông qua router dynamic parameter `params.lang` (mặc định là 'zh').
*   **Trạng thái tương tác**:
    *   `answers`: Bản đồ lưu câu trả lời của người dùng dạng `{ [question_id]: option_id }` hoặc `{ [question_id]: text_input }`.
    *   `timeRemaining`: Đếm ngược thời gian thi (tính bằng giây). Tự động kích hoạt tính năng nộp bài (`handleSubmit`) khi thời gian trở về `0`.
    *   `isSubmitted`: Trạng thái đã nộp bài, kích hoạt giao diện hiển thị kết quả và giải thích chi tiết.
    *   `score`: Điểm số đạt được, tính toán tức thì dựa trên trọng số điểm `points` của từng câu hỏi khớp với `correct_answer`.
*   **Lưu trữ trạng thái cục bộ (State Persistence)**: Tích hợp module `examState` (`loadExamState`, `saveExamState`, `clearExamState`) lưu tiến trình làm bài và thời lượng audio vào `localStorage` của trình duyệt. Giúp phục hồi bài thi nguyên vẹn khi người dùng lỡ tải lại trang hoặc mất kết nối mạng.

---

## 2. Tính Năng Tối Thiểu (Minimum Required Features)

Để đảm bảo chất lượng vận hành và trải nghiệm học viên chuẩn quốc tế, hệ thống phải đáp ứng các tính năng tối thiểu sau:

1.  **Đa giao diện ngôn ngữ (English UI vs. Chinese UI)**:
    *   Đề thi hiển thị bằng tiếng Anh (`lang = en`): Hướng dẫn, nhãn nút (Submit, Next, Question List), tiêu đề phụ và giải thích được dịch thuật chuẩn hóa sang tiếng Anh.
    *   Đề thi hiển thị bằng tiếng Trung (`lang = zh`): Phù hợp với đối tượng học viên muốn rèn luyện tư duy hoàn toàn bằng tiếng Trung, hỗ trợ phiên âm pinyin đi kèm.
2.  **Bộ phát Audio thông minh kép (Dual Audio Engine)**:
    *   *Main Audio Player*: Phát luồng âm thanh chung cho toàn bộ kỹ năng nghe.
    *   *Segment Audio Player*: Đối với các câu hỏi đơn lẻ có mốc thời gian (`audio_start_time` và `audio_end_time`), hệ thống tự động trích xuất và phát đúng phân đoạn âm thanh đó, tự động dừng phát khi chạm mốc kết thúc (`activeSegmentEndTimeRef`).
    *   *Centralized Control*: Đồng bộ tốc độ phát (`playbackRate`) và âm lượng (`volume`) từ cấu hình chung của người học (`useSettingsStore`).
3.  **Tự động lưu và Tiếp tục làm bài (Auto-Save & Resume)**:
    *   Lưu liên tục trạng thái đáp án và thời gian đếm ngược sau mỗi lượt chọn hoặc điền câu trả lời.
    *   Khi nộp bài thành công, hệ thống xóa bỏ trạng thái tạm thời trong bộ nhớ để tránh xung đột cho các lần thi tiếp theo.
4.  **Tương tác Hình ảnh Nâng cao (Image Lightbox & Zoom)**:
    *   Cho phép người dùng nhấn vào bất kỳ hình ảnh nào trong đề bài hoặc đáp án để phóng to xem chi tiết mà không làm vỡ bố cục giao diện hoặc tải lại trang. Hỗ trợ thanh điều hướng thu phóng (`lightboxZoom`).
5.  **Bảng điều khiển câu hỏi trực quan (Interactive Question Navigator)**:
    *   *Trước khi nộp bài*: Đánh dấu màu các câu đã làm (màu Primary) và chưa làm (màu viền nhạt) để người dùng kiểm soát tiến độ.
    *   *Sau khi nộp bài*: Tô màu xanh lá đối với câu trả lời Đúng, tô màu đỏ đối với câu trả lời Sai để người dùng dễ dàng tra cứu nhanh các lỗi sai.
6.  **Tích hợp Gamification (Streak & XP)**:
    *   Tích hợp trực tiếp với `useGamificationStore` để ghi nhận điểm số, tăng vọt thanh tiến trình, cộng điểm kinh nghiệm (XP) và duy trì chuỗi học tập (Streak) ngay sau khi nộp bài thi thành công.

---

## 3. Cấu Trúc Đề Thi HSK Chi Tiết (Detailed HSK Exam Structure)

Dựa trên phân tích từ dữ liệu đề thi mẫu thực tế, cấu trúc đề thi của từng cấp độ mới (chuẩn 2026) được thiết kế linh hoạt với các loại câu hỏi chuyên biệt:

### 3.1. HSK 1 (`HSK1_NEW_UUID_003.json`)
*   **Chỉ số**: 40 câu hỏi | Thời gian: 40 phút | Tổng điểm: 200 điểm | Điểm đạt: 120 điểm.
*   **Phân bổ Phần thi**:
    *   `Listening` (Phần 1 - 4 | 20 câu | 100 điểm):
        *   *Part 1*: 5 câu `true_false`. Người dùng nghe audio từ đơn và nhìn tranh (VD: "医院. (Yīyuàn)" đi kèm mô tả tòa nhà bệnh viện có chữ thập đỏ) để phán đoán Đúng/Sai.
        *   *Part 2*: 5 câu `multiple_choice` (3 lựa chọn). Nghe câu ngắn và chọn hình ảnh phù hợp.
        *   *Part 3*: 5 câu `multiple_choice`. Nghe đoạn đối thoại ngắn 2 câu (Nam - Nữ) và chọn hình ảnh đáp án.
        *   *Part 4*: 5 câu `multiple_choice`. Nghe câu hỏi ngắn và lựa chọn đáp án văn bản thích hợp.
    *   `Reading` (Phần 1 - 4 | 20 câu | 100 điểm):
        *   *Part 1*: 5 câu `true_false`. Đọc từ vựng tiếng Trung kèm pinyin và nhìn hình ảnh để xác định Đúng/Sai.
        *   *Part 2*: 5 câu `multiple_choice`. Đọc câu và chọn bức tranh tương thích trong danh sách A, B, C.
        *   *Part 3*: 5 câu `multiple_choice`. Nối câu hỏi với câu trả lời phù hợp trong ngữ cảnh hội thoại.
        *   *Part 4*: 5 câu `multiple_choice`. Điền từ vào ô trống (dạng trắc nghiệm lựa chọn từ phù hợp trong danh mục cho sẵn).

### 3.2. HSK 3 (`HSK3_NEW_UUID_001.json`)
*   **Chỉ số**: 70 câu hỏi | Thời gian: 90 phút | Tổng điểm: 300 điểm | Điểm đạt: 180 điểm.
*   **Phân bổ Phần thi**:
    *   `Listening` (Phần 1 - 4 | 30 câu | 120 điểm):
        *   *Part 1*: 10 câu `multiple_choice` (3 lựa chọn). Nghe đối thoại ngắn và chọn hình ảnh mô tả chính xác.
        *   *Part 2*: 10 câu `multiple_choice`. Nghe đoạn hội thoại dài và chọn câu trả lời đúng cho câu hỏi.
        *   *Part 3*: 5 câu `multiple_choice`. Nghe một đoạn độc thoại/truyện ngắn và trả lời câu hỏi trắc nghiệm.
        *   *Part 4*: 5 câu `multiple_choice`. Nghe một đoạn văn dài hơn, trả lời câu hỏi phân tích thông tin.
    *   `Reading` (Phần 1 - 4 | 30 câu | 120 điểm):
        *   *Part 1*: 10 câu `multiple_choice`. Đọc các đoạn hội thoại ngắn và chọn câu phản hồi hợp lý nhất.
        *   *Part 2*: 10 câu `multiple_choice`. Đọc các đoạn văn ngắn và chọn ý kiến đúng với nội dung bài đọc.
        *   *Part 3*: 5 câu `multiple_choice`. Điền từ vào chỗ trống trong đoạn văn.
        *   *Part 4*: 5 câu `multiple_choice`. Sắp xếp các câu văn cho trước thành một đoạn văn hoàn chỉnh có logic.
    *   `Writing` (Phần 1 - 2 | 10 câu | 60 điểm):
        *   *Part 1 (`ordering`)*: 5 câu sắp xếp từ vựng thành câu hoàn chỉnh. Người dùng nhận được chuỗi từ phân tách bởi dấu gạch chéo (VD: `把 / 电脑 / 请 / 关上`), yêu cầu viết lại câu đúng ngữ pháp (`请把电脑关上。`).
        *   *Part 2 (`fill_blank`)*: 5 câu điền chữ Hán vào chỗ trống dựa trên gợi ý phiên âm pinyin (VD: `没关系，下（ cì ）再去 cũng được。` -> người dùng phải điền đúng chữ Hán `次`).

### 3.3. HSK 4 (`HSK4_NEW_UUID_001.json`)
*   **Chỉ số**: 95 câu hỏi | Thời gian: 105 phút | Tổng điểm: 300 điểm | Điểm đạt: 180 điểm.
*   **Phân bổ Phần thi**:
    *   `Listening` (Phần 1 - 3 | 40 câu | 100 điểm):
        *   *Part 1*: 10 câu `true_false`. Nghe đoạn hội thoại trung bình hoặc đoạn văn ngắn để phán đoán tính đúng đắn của một câu khẳng định cho trước.
        *   *Part 2*: 15 câu `multiple_choice` (4 lựa chọn). Nghe đối thoại giữa 2 người và chọn đáp án thích hợp.
        *   *Part 3*: 15 câu `multiple_choice` (4 lựa chọn). Nghe các câu chuyện nhỏ hoặc phỏng vấn để chọn đáp án đúng.
    *   `Reading` (Phần 1 - 3 | 40 câu | 100 điểm):
        *   *Part 1*: 10 câu `multiple_choice`. Điền từ thích hợp vào chỗ trống trong câu đơn hoặc đoạn hội thoại ngắn.
        *   *Part 2*: 10 câu `multiple_choice`. Sắp xếp thứ tự các câu đơn (A, B, C, D) thành đoạn văn logic.
        *   *Part 3*: 20 câu `multiple_choice`. Đọc hiểu đoạn văn trung bình và trả lời các câu hỏi trắc nghiệm liên quan.
    *   `Writing` (Phần 1 - 2 | 15 câu | 100 điểm):
        *   *Part 1 (`ordering`)*: 10 câu sắp xếp từ vựng bị đảo lộn cấu trúc ngữ pháp thành câu chuẩn chỉnh.
        *   *Part 2 (`essay`)*: 5 câu viết câu tự luận ngắn. Đề bài cung cấp một hình ảnh mô tả kèm một từ khóa gợi ý (VD: Từ khóa "乒乓球" đi kèm hình ảnh học sinh đang chơi bóng bàn. Người dùng tự viết một câu hoàn chỉnh như "他们正在操场上打乒乓球。").

### 3.4. HSK 6 (`HSK6_NEW_UUID_001.json`)
*   **Chỉ số**: 101 câu hỏi | Thời gian: 140 phút | Tổng điểm: 300 điểm | Điểm đạt: 180 điểm.
*   **Phân bổ Phần thi**:
    *   `Listening` (Phần 1 - 3 | 50 câu | 100 điểm):
        *   *Part 1*: 15 câu `multiple_choice`. Nghe đoạn văn ngắn, chọn câu có ý nghĩa trùng khớp nhất trong 4 phương án.
        *   *Part 2*: 15 câu `multiple_choice`. Nghe các đoạn phỏng vấn báo chí hoặc hội thoại dài, trả lời các câu hỏi đi kèm.
        *   *Part 3*: 20 câu `multiple_choice`. Nghe các bài phát biểu, giảng dạy hoặc báo cáo khoa học dài, trả lời câu hỏi trắc nghiệm.
    *   `Reading` (Phần 1 - 4 | 50 câu | 100 điểm):
        *   *Part 1*: 10 câu `multiple_choice`. Chọn câu có lỗi sai về ngữ pháp hoặc cấu trúc dùng từ (Bệnh cú - 语病).
        *   *Part 2*: 10 câu `multiple_choice`. Điền tổ hợp từ phù hợp vào nhiều chỗ trống trong đoạn văn ngắn.
        *   *Part 3*: 10 câu `multiple_choice`. Điền các câu văn dài vào vị trí khuyết thiếu trong một văn bản lớn.
        *   *Part 4*: 20 câu `multiple_choice`. Đọc hiểu chuyên sâu các văn bản khoa học xã hội, lịch sử, kinh tế và trả lời câu hỏi.
    *   `Writing` (Phần 1 | 1 câu | 100 điểm):
        *   *Part 1 (`essay`)*: Viết tóm tắt văn bản. Học viên được đọc một bài viết tự sự dài khoảng 1000 chữ trong vòng 10 phút. Sau 10 phút, văn bản gốc sẽ ẩn đi. Học viên phải tự viết một bài tóm tắt khoảng 400 chữ dựa trên trí nhớ mà không được đưa quan điểm cá nhân vào bài viết.

### 3.5. HSK 7-9 (`HSK7_9_NEW_UUID_002.json`)
*   **Chỉ số**: 98 câu hỏi | Thời gian: 210 phút | Tổng điểm: 500 điểm | Điểm đạt: 260 điểm.
*   **Phân bổ Phần thi**:
    *   `Listening` (Phần 1 - 3 | 40 câu | 100 điểm):
        *   *Part 1*: 15 câu `multiple_choice`. Nghe tin tức thời sự hoặc báo cáo ngắn.
        *   *Part 2*: 15 câu `multiple_choice`. Nghe tọa đàm học thuật, tranh luận đa chiều.
        *   *Part 3*: 10 câu `multiple_choice`. Nghe bài giảng chuyên sâu (VD: Sinh học thần kinh, Biến đổi khí hậu).
    *   `Reading` (Phần 1 - 3 | 47 câu | 100 điểm):
        *   *Part 1*: 15 câu `multiple_choice`. Đọc điền từ hoặc sửa lỗi cụm từ học thuật.
        *   *Part 2*: 7 câu `multiple_choice`. Đọc hiểu các đoạn trích Văn ngôn văn (Văn bản cổ Trung Quốc).
        *   *Part 3*: 25 câu `multiple_choice`. Đọc hiểu văn bản nghiên cứu khoa học, tài liệu triết học dài.
    *   `Writing` (Phần 1 - 2 | 2 câu | 100 điểm):
        *   *Part 1 (`essay`)*: Viết phân tích biểu đồ (40 điểm). Thí sinh nhìn biểu đồ số liệu/hình vẽ và viết một bài mô tả khách quan khoảng 200 chữ giải thích xu hướng số liệu.
        *   *Part 2 (`essay`)*: Viết nghị luận xã hội (60 điểm). Thí sinh nhận được một chủ đề tranh luận (VD: Lợi ích và tác hại của việc tiền kỹ thuật số thay thế hoàn toàn tiền giấy) và phải viết bài nghị luận khoảng 400 chữ để bảo vệ luận điểm.
    *   `Translation` (Phần 1 - 2 | 4 câu | 100 điểm):
        *   *Part 1 (`multiple_choice`)*: Dịch viết (Bút dịch). Lựa chọn bản dịch học thuật tốt nhất từ tiếng Trung sang tiếng Anh hoặc ngược lại.
        *   *Part 2 (`multiple_choice` / audio)*: Dịch nói (Phiên dịch). Nghe đoạn nói bằng tiếng Anh/tiếng Trung và lựa chọn phương án phiên dịch đồng thời chuẩn xác nhất.
    *   `Speaking` (Phần 1 | 5 câu | 100 điểm):
        *   *Part 1 (`multiple_choice`)*: Thuyết trình học thuật. Phân tích tài liệu và chọn dàn ý thuyết trình tối ưu nhất.

---

## 4. Thiết Kế Giao Diện & Trải Nghiệm Đa Thiết Bị (Responsive & Multi-Language UI/UX)

Để đáp ứng yêu cầu hiển thị tốt trên cả **Mobile** và **PC** cùng với 2 giao diện ngôn ngữ, hệ thống sử dụng các mẫu thiết kế linh hoạt (Design Patterns):

```
+-----------------------------------------------------------------------+
|  [Logo XiaoYue]         [Time Remaining: 59:12]       [Button: Leave] |
+-----------------------------------------------------------------------+
|  (PC Layout - Dual Column)                                            |
|                                                                       |
|  [LEFT PANEL: 2/3 Width]               [RIGHT PANEL: 1/3 Width]       |
|  +-----------------------------------+ +----------------------------+ |
|  | Section: Listening (Part 1)       | | [Question Map]             | |
|  | Instruction: 判断对错              | | [ 1 ] [ 2 ] [ 3 ] [ 4 ]   | |
|  |                                   | | [ 5 ] [ 6 ] [ 7 ] [ 8 ]   | |
|  | Question 1:                       | |                            | |
|  | +-------------------------------+ | | [Submit Button]            | |
|  | | Image Description             | | +----------------------------+ |
|  | | [Audio Segment Player]        | |                                | |
|  | |                               | |                                | |
|  | | (A) True     (B) False        | |                                | |
|  | +-------------------------------+ | |                                | |
|  +-----------------------------------+ +----------------------------+ |
+-----------------------------------------------------------------------+
```

### 4.1. Giao diện Tiếng Anh (English UI) vs. Giao diện Tiếng Trung (Chinese UI)
*   **Hỗ trợ dịch thuật bản địa (Localization)**:
    *   Các nhãn trạng thái và thông báo hệ thống được quản lý thông qua file ngôn ngữ `locale` tương ứng với đường dẫn `/[lang]/exam/`.
    *   Thiết kế các nút bấm có độ dài co giãn linh hoạt (`min-w` kết hợp padding) để tránh lỗi tràn khung chữ khi dịch từ tiếng Trung (ngắn gọn) sang tiếng Anh (dài hơn).
*   **Trình bày Pinyin**:
    *   Trong giao diện tiếng Trung (`zh`), các câu hỏi hoặc đoạn văn đọc hiểu bổ sung thẻ `<ruby>` để hiển thị phiên âm pinyin nhỏ phía trên chữ Hán gốc đối với các cấp độ HSK thấp (HSK 1 - HSK 3) giúp người học dễ theo dõi.
    *   Ví dụ: `<ruby>医<rt>yī</rt>院<rt>yuàn</rt></ruby>`.

### 4.2. Giao diện Máy tính (PC / Desktop View)
*   **Bố cục hai cột (Dual-Column Split)**:
    *   *Cột trái (2/3 chiều rộng)*: Vùng cuộn chính hiển thị nội dung các phần thi (`sections`), hướng dẫn làm bài và danh sách câu hỏi.
    *   *Cột phải (1/3 chiều rộng)*: Sidebar chứa bảng bản đồ câu hỏi (`Question Map`), bộ đếm thời gian thi và nút **Nộp Bài**. Thiết kế dạng `sticky` cố định bên phải màn hình khi người dùng cuộn xem câu hỏi ở cột trái.
*   **Hộp công cụ kỹ năng đọc (Reading Sidebar)**:
    *   Khi người dùng làm tới phần thi đọc (`Reading`), nút mở ngăn đọc (`Reading Drawer`) xuất hiện, cho phép xem song song văn bản đọc hiểu bên cạnh danh sách câu hỏi trắc nghiệm để tránh việc phải cuộn lên cuộn xuống liên tục.

### 4.3. Giao diện Di động (Mobile / Tablet View)
*   **Bố cục một cột tinh gọn (Single-Column Fluid)**:
    *   Cột phải (Sidebar) bị ẩn đi để nhường toàn bộ không gian cho câu hỏi.
    *   Bảng bản đồ câu hỏi được đưa vào một **Ngăn trượt (Mobile Drawer)** kích hoạt bởi nút bấm nổi biểu tượng lưới 9 ô vuông ở góc màn hình (`fixed right-0 top-1/2 -translate-y-1/2`).
*   **Ngăn chặn lỗi phóng to cưỡng bức trên iOS (Prevent Auto-Zoom)**:
    *   Trình duyệt Safari trên iOS sẽ tự động phóng to trang web vào ô nhập liệu nếu kích cỡ chữ (`font-size`) của ô nhập liệu đó nhỏ hơn `16px`. Để triệt tiêu trải nghiệm khó chịu này, hệ thống áp dụng quy tắc CSS: ép buộc tất cả văn bản nhập liệu và nhãn đáp án đạt kích thước tối thiểu **`16px` (`text-base` hoặc `1rem`)** trên các thiết bị di động có chiều rộng màn hình `< 768px`.
*   **Tương thích cảm ứng (Touch Friendly Controls)**:
    *   Khoảng cách giữa các nút đáp án trắc nghiệm tăng lên tối thiểu `12px` (khoảng cách an toàn để tránh chạm nhầm đáp án).
    *   Tất cả các thẻ đáp án sử dụng hiệu ứng phản hồi xúc giác giả lập thông qua các class Tailwind `active:scale-98` và `transition-all`.
*   **Bộ sưu tập hình ảnh dạng lưới (Image Responsive Grid)**:
    *   Khi tùy chọn đáp án chỉ có hình ảnh không có văn bản (`isImageOnly`), trên Mobile giao diện sẽ tự động chuyển từ hiển thị 3 cột thành lưới 1 hoặc 2 cột để hình ảnh hiển thị rõ nét nhất, hỗ trợ nhấp đúp để xem lightbox phóng to.

---

## 5. Quy tắc Thiết kế Visual & Micro-Animations (Dựa trên DESIGN.md)

Để nâng cao tính thẩm mỹ cao cấp (Premium Aesthetics), giao diện phải tuân thủ nghiêm ngặt các quy tắc sau:

*   **Bảng màu chỉ báo**:
    *   Sử dụng màu Indigo/Violet gradient (`var(--accent-gradient-start)` to `var(--accent-gradient-end)`) cho các trạng thái nổi bật, VIP, hoặc báo hiệu chấm điểm.
    *   Sử dụng hệ thống màu chỉ báo điểm số dịu mắt: màu xanh Emerald (`#10B981`) cho điểm Đạt, màu đỏ Coral (`#EF4444`) cho điểm chưa Đạt.
*   **Kiểu chữ**:
    *   Sử dụng font **Lexend** cho các tiêu đề lớn, con số điểm và nút điều hướng để tạo sự trẻ trung, hiện đại.
    *   Sử dụng font **Inter** cho các câu hỏi, đoạn văn bản đọc hiểu và phần giải nghĩa học thuật để tối ưu khả năng đọc.
*   **Chuyển động mượt mà**:
    *   *Pulse-ring*: Vòng tròn phát sáng nhịp nhàng xung quanh nút ghi âm/nghe phân đoạn.
    *   *Slide-up*: Nội dung câu hỏi tiếp theo sẽ trượt nhẹ từ dưới lên khi người dùng nhấn chuyển câu.
    *   *Progress-stroke*: Vạch tiến trình chạy xung quanh số điểm đạt được sau khi nộp bài thi.
