# TÀI LIỆU MÔ TẢ API — XIAOYUEDICT

> **API Version:** v1
> **Base URL:** `https://cnendict.xyz/api/v1/` (Production) | `http://localhost:80/api/v1/` (Development)
> **Authentication:** JWT trong httpOnly Cookie (CookieJWTAuthentication)
> **Content-Type:** `application/json` (mặc định) | `multipart/form-data` (upload file)
> **Phiên bản tài liệu:** 1.0 | Cập nhật: 2026-07-25

---

## Quy Ước Chung

### Authentication
- Tất cả endpoint yêu cầu đăng nhập sẽ đọc JWT từ cookie `access_token` (httpOnly, Secure, SameSite=Lax).
- Endpoint hỗ trợ Guest sẽ đọc header `X-Guest-ID` khi không có JWT.
- Token lifetime: Access = 60 phút, Refresh = 24 giờ.

### Rate Limiting
| Scope | Giới hạn |
|---|---|
| Anonymous | 30 requests/phút |
| Authenticated User | 60 requests/phút |
| Exam Fetch | 10 requests/phút |

### Response Format
```json
{
  "status": "success" | "error",
  "data": { ... },
  "message": "string (optional)"
}
```

### Error Response
```json
{
  "detail": "Error message",
  "code": "error_code"
}
```

### HTTP Status Codes
| Code | Ý nghĩa |
|---|---|
| 200 | OK — Thành công |
| 201 | Created — Tạo mới thành công |
| 202 | Accepted — Task đã được enqueue (async) |
| 400 | Bad Request — Dữ liệu không hợp lệ |
| 401 | Unauthorized — Chưa đăng nhập |
| 403 | Forbidden — Không có quyền |
| 404 | Not Found — Không tìm thấy |
| 429 | Too Many Requests — Vượt rate limit |
| 500 | Internal Server Error |

---

## 1. Users — Quản lý Người dùng

**Prefix:** `/api/v1/users/`

### 1.1. `POST /users/register/`
Đăng ký tài khoản mới.

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | [x] | Tên đăng nhập |
| `email` | string | [x] | Email |
| `password` | string | [x] | Mật khẩu |

**Response:** `201 Created` — User object + JWT cookies set.

---

### 1.2. `POST /users/firebase-login/`
Đăng nhập bằng Firebase ID Token.

| Field | Type | Required | Description |
|---|---|---|---|
| `id_token` | string | [x] | Firebase ID Token từ client SDK |

**Response:** `200 OK` — Set `access_token` & `refresh_token` cookies.

---

### 1.3. `GET /users/profile/` [AUTH]
Lấy thông tin profile người dùng hiện tại.

**Response:**
```json
{
  "id": "uuid",
  "username": "string",
  "email": "string",
  "bio": "string",
  "avatar": "url",
  "firebase_uid": "string"
}
```

### 1.4. `PUT /users/profile/` [AUTH]
Cập nhật profile (bio, avatar).

### 1.5. `POST /users/password/change/` [AUTH]
Đổi mật khẩu. Body: `{ old_password, new_password }`.

### 1.6. `POST /users/token/`
Lấy JWT token pair (email + password login).

### 1.7. `POST /users/token/refresh/`
Refresh access token từ refresh_token cookie.

### 1.8. `POST /users/token/logout/`
Xóa JWT cookies.

### 1.9. `GET /users/ws-token/` [AUTH]
Lấy short-lived token cho WebSocket connection.

### 1.10. `GET /users/azure-speech-token/` [AUTH]
Lấy Azure Speech SDK token cho phát âm realtime.

---

## 2. Dictionary ZH — Từ điển Tiếng Trung

**Prefix:** `/api/v1/dictionary/zh/`

### 2.1. `GET /dictionary/zh/search/`
Tìm kiếm từ vựng tiếng Trung (Full-text + Trigram + Jieba).

| Param | Type | Required | Description |
|---|---|---|---|
| `q` | string | [x] | Từ khóa (tiếng Trung / Pinyin / Hán Việt / tiếng Việt) |
| `hsk` | string | — | Lọc theo cấp HSK (1-9) |
| `page` | int | — | Trang (default: 1) |

**Response:** `200 OK` — Paginated list of ZhWord objects with examples.

---

### 2.2. `POST /dictionary/zh/search/batch/`
Tìm kiếm hàng loạt (batch lookup).

| Field | Type | Required | Description |
|---|---|---|---|
| `words` | string[] | [x] | Danh sách từ cần tra |

---

### 2.3. `POST /dictionary/zh/translate/` [AUTH]
Dịch văn bản tự do Trung → Việt bằng Gemini AI (async Celery task).

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | [x] | Văn bản tiếng Trung cần dịch |

**Response:** `202 Accepted` — `{ "task_id": "celery-task-id" }`

---

### 2.4. `GET /dictionary/zh/translate/status/{task_id}/`
Kiểm tra trạng thái task dịch thuật.

**Response:**
```json
{
  "status": "PENDING" | "SUCCESS" | "FAILURE",
  "result": "Bản dịch tiếng Việt (nếu SUCCESS)"
}
```

### 2.5. `GET /dictionary/zh/radical-search/`
Tìm kiếm từ theo bộ thủ (radical).

| Param | Type | Required | Description |
|---|---|---|---|
| `radical` | string | [x] | Bộ thủ cần tìm |

---

## 3. Dictionary EN — Từ điển Tiếng Anh

**Prefix:** `/api/v1/dictionary/en/`

### 3.1. `GET /dictionary/en/search/`
Tìm kiếm từ vựng tiếng Anh (B-tree prefix + Trigram fuzzy).

| Param | Type | Required | Description |
|---|---|---|---|
| `q` | string | [x] | Từ khóa |

### 3.2. `POST /dictionary/en/translate/` [AUTH]
Dịch văn bản Anh → Việt bằng AI (async).

### 3.3. `GET /dictionary/en/translate/status/{task_id}/`
Kiểm tra trạng thái dịch thuật.

---

## 4. Assessments — Đánh giá Phát âm AI

**Prefix:** `/api/v1/assessments/`

### 4.1. `POST /assessments/submit/` [AUTH]
Upload file audio để chấm điểm phát âm AI.

| Field | Type | Required | Description |
|---|---|---|---|
| `audio` | File | [x] | File audio (webm/wav, max 20MB) |
| `text` | string | [x] | Văn bản gốc để so sánh |
| `language` | string | [x] | `en` hoặc `zh` |

**Content-Type:** `multipart/form-data`

**Response:** `202 Accepted`
```json
{
  "assessment_id": "uuid",
  "task_id": "celery-task-id",
  "queue": "queue_paid" | "queue_free" | "queue_guest"
}
```

**Queue Routing:** Dựa trên tier đăng ký → `UserTierRouter` tự động phân luồng.

---

### 4.2. `GET /assessments/status/{task_id}/` [AUTH]
Polling trạng thái chấm điểm.

**Response:**
```json
{
  "status": "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED",
  "score": 85.5,
  "result_data": {
    "overall_score": 85.5,
    "phoneme_scores": [ { "phoneme": "h", "score": 90 }, ... ],
    "word_scores": [ ... ]
  }
}
```

### 4.3. `POST /assessments/spellcheck/`
Kiểm tra chính tả văn bản (pyspellchecker).

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | [x] | Văn bản cần kiểm tra |

### 4.4. `POST /assessments/refund/` [AUTH]
Yêu cầu hoàn trả coin khi chấm điểm thất bại.

---

## 5. Exams — Quản lý Đề thi

**Prefix:** `/api/v1/exams/`

### 5.1. `GET /exams/`
Danh sách đề thi.

| Param | Type | Required | Description |
|---|---|---|---|
| `level` | string | — | Lọc theo cấp (HSK 1, HSK 3...) |
| `language` | string | — | Lọc theo ngôn ngữ (en/zh) |

**Response:** `200 OK` — Paginated list of Exam summaries.

### 5.2. `GET /exams/{exam_id}/`
Chi tiết đề thi (bao gồm sections, questions, options).

**Response:** `200 OK` — Full exam with nested sections → questions → options.
**Cache:** Redis cache, evicted qua Django signals.

### 5.3. `GET /exams/{exam_id}/audio-stream/`
Stream file audio của section (proxy qua GCS).

---

## 6. Notes — Sổ tay Từ vựng

**Prefix:** `/api/v1/notes/`

### 6.1. `GET /notes/notebooks/` [AUTH]
Danh sách sổ tay của user.

### 6.2. `POST /notes/notebooks/` [AUTH]
Tạo sổ tay mới.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | [x] | Tên sổ |
| `lang` | string | — | `zh` (default) hoặc `en` |
| `description` | string | — | Mô tả |

### 6.3. `GET/PUT/DELETE /notes/notebooks/{notebook_id}/` [AUTH]
CRUD sổ tay.

### 6.4. `GET /notes/notebooks/{notebook_id}/words/` [AUTH]
Danh sách từ trong sổ tay.

### 6.5. `POST /notes/notebooks/{notebook_id}/words/` [AUTH]
Thêm từ vào sổ tay.

| Field | Type | Required | Description |
|---|---|---|---|
| `vocabulary` | string | [x] | Từ vựng |
| `pinyin` | string | — | Phiên âm |
| `meaning` | string | — | Nghĩa |
| `note` | string | — | Ghi chú cá nhân |

### 6.6. `GET/PUT/DELETE /notes/notebooks/{notebook_id}/words/{word_id}/` [AUTH]
CRUD từ vựng trong sổ.

### 6.7. `POST /notes/notebooks/{notebook_id}/export-pdf/` [AUTH]
Xuất sổ tay ra PDF (async Celery task).

| Field | Type | Required | Description |
|---|---|---|---|
| `export_type` | string | — | `normal` hoặc `stroke` (phân rã nét) |

**Response:** `202 Accepted` — `{ "task_id": "uuid" }`

### 6.8. `GET /notes/notebooks/{notebook_id}/export-pdf/limits/` [AUTH]
Kiểm tra giới hạn xuất PDF (theo tier).

### 6.9. `GET /notes/notebooks/export-pdf/status/{task_id}/` [AUTH]
Polling trạng thái xuất PDF.

### 6.10. `GET /notes/notebooks/export-pdf/download/{task_id}/` [AUTH]
Download file PDF đã xuất.

### 6.11. `GET /notes/lookup/`
Tra cứu nhanh từ điển (dùng cho autocomplete khi thêm từ vào sổ).

### 6.12. `GET /notes/system-notebooks/`
Danh sách sổ tay hệ thống (HSK levels).

### 6.13. `GET /notes/system-notebooks/{key}/words/`
Lấy từ trong sổ tay hệ thống.

### 6.14. `POST /notes/clone-system-notebook/` [AUTH]
Clone sổ tay hệ thống vào tài khoản cá nhân.

---

## 7. Flashcard Exercises — Bài tập Flashcard

**Prefix:** `/api/v1/flashcard/`

### 7.1. `POST /flashcard/exercises/` [AUTH]
Sinh bài tập AI cho từ vựng (cached vĩnh viễn).

| Field | Type | Required | Description |
|---|---|---|---|
| `word` | string | [x] | Từ vựng |
| `lang` | string | — | `zh` (default) hoặc `en` |
| `exercise_type` | string | [x] | `reading` hoặc `listening` |

**Response:** `200 OK` (cache hit) hoặc `202 Accepted` (generating).

### 7.2. `POST /flashcard/exercises/complete/` [AUTH]
Đánh dấu đã hoàn thành bài tập (lưu history).

### 7.3. `POST /flashcard/check-writing/` [AUTH]
Luyện viết sâu theo từ (AI chấm điểm, trừ coin).

| Field | Type | Required | Description |
|---|---|---|---|
| `sentence` | string | [x] | Đoạn văn/câu do học sinh viết |
| `target_word` | string | [x] | Từ vựng mục tiêu |
| `lang` | string | — | `zh` (default) hoặc `en` |

### 7.4. `POST /flashcard/check-general-writing/` [AUTH]
Luyện viết tự do (không cần target word).

### 7.5. `GET /flashcard/writing-tasks/pending/` [AUTH]
Danh sách writing tasks đang chờ xử lý.

### 7.6. `GET /flashcard/writing-tasks/{task_id}/` [AUTH]
Chi tiết kết quả chấm writing task.

---

## 8. Media — Hình ảnh & TTS

**Prefix:** `/api/v1/media/`

### 8.1. `GET /media/image/{lang}/{word_id}/`
Lấy hình ảnh minh họa của từ vựng (AI-generated, cached trên GCS).

**Response:**
```json
{
  "status": "ready" | "generating" | "not_found",
  "image_url": "https://storage.googleapis.com/..."
}
```

### 8.2. `POST /media/image/report/` [AUTH]
Báo cáo hình ảnh sai/không phù hợp.

### 8.3. `POST /media/tts/`
Trigger sinh audio TTS cho từ/câu.

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | [x] | Văn bản cần phát âm |
| `lang` | string | [x] | `zh` hoặc `en` |

### 8.4. `POST /media/tts/batch-status/`
Kiểm tra trạng thái TTS hàng loạt.

### 8.5. `POST /media/tts/batch-trigger/`
Trigger sinh TTS hàng loạt.

---

## 9. Subscriptions — Đăng ký & Thanh toán

**Prefix:** `/api/v1/subscriptions/`

### 9.1. `GET /subscriptions/me/` [AUTH]
Thông tin đăng ký hiện tại.

**Response:**
```json
{
  "tier": "Free" | "Plus" | "Pro" | "Premium",
  "start_date": "datetime",
  "end_date": "datetime | null",
  "is_active": true,
  "pending_downgrade_tier": "Free | null"
}
```

### 9.2. `GET /subscriptions/history/` [AUTH]
Lịch sử thay đổi gói.

### 9.3. `GET /subscriptions/usage/` [AUTH]
Thông tin sử dụng bandwidth hiện tại.

### 9.4. `GET /subscriptions/plans/`
Danh sách gói đăng ký (cached, signal eviction).

### 9.5. `POST /subscriptions/register/` [AUTH]
Đăng ký/nâng cấp gói (tạo PaymentOrder).

| Field | Type | Required | Description |
|---|---|---|---|
| `tier` | string | [x] | Plus / Pro / Premium |

**Response:** `201 Created`
```json
{
  "order_code": "CNEN-abc12345",
  "amount": 99000,
  "transfer_content": "CNEN abc12345",
  "bank_code": "BANK",
  "account_number": "123456789",
  "expires_at": "datetime"
}
```

### 9.6. `POST /subscriptions/sepay-webhook/`
Webhook nhận callback từ SePay khi thanh toán thành công.

**Headers:** `Authorization: Webhook {SEPAY_WEBHOOK_SECRET}`

### 9.7. `GET /subscriptions/payment-status/{order_id}/` [AUTH]
Polling trạng thái đơn thanh toán.

---

## 10. Gamification — Game hóa

**Prefix:** `/api/v1/gamification/`

### 10.1. `GET /gamification/dashboard/` [AUTH]
Dashboard tổng hợp: streaks, coins, level, daily activity.

### 10.2. `GET /gamification/streaks/` [AUTH]
Thông tin chuỗi học tập (current_streak, max_streak).

### 10.3. `GET/PUT /gamification/targets/` [AUTH]
Mục tiêu học tập hàng ngày.

### 10.4. `POST /gamification/history/` [AUTH]
Ghi nhận lịch sử học tập.

### 10.5. `GET /gamification/activities/` [AUTH]
Lịch hoạt động (calendar view).

### 10.6. `POST /gamification/study-session/` [AUTH]
Tạo phiên học flashcard mới.

| Field | Type | Required | Description |
|---|---|---|---|
| `lang` | string | [x] | zh / en |
| `cards` | array | [x] | Danh sách card_id, word |

### 10.7. `POST /gamification/study-session/{session_id}/finish/` [AUTH]
Kết thúc phiên học, tính coin kiếm được.

### 10.8. `GET /gamification/wallet/` [AUTH]
Thông tin ví coin (paid_balance, free_balance, shop_balance).

| Param | Type | Required | Description |
|---|---|---|---|
| `lang` | string | — | zh / en (default: both) |

### 10.9. `POST /gamification/wallet/purchase/` [AUTH]
Tạo đơn mua coin bằng SePay.

### 10.10. `GET /gamification/wallet/purchase/{order_id}/` [AUTH]
Polling trạng thái đơn mua coin.

### 10.11. `GET /gamification/coin-config/` [AUTH]
Cấu hình chi phí coin cho tier hiện tại.

### 10.12. `GET /gamification/wallet/all-configs/` [AUTH]
Tất cả cấu hình coin (dùng cho bảng so sánh tiers).

### 10.13. `GET /gamification/level/` [AUTH]
Level & EXP tất cả ngôn ngữ.

### 10.14. `GET /gamification/level/{lang}/` [AUTH]
Level & EXP cho ngôn ngữ cụ thể.

### 10.15. `GET /gamification/inventory/` [AUTH]
Kho vật phẩm đã nhận.

### 10.16. `POST /gamification/inventory/{item_id}/equip/` [AUTH]
Trang bị/gỡ vật phẩm.

### 10.17. `GET /gamification/rewards/preview/` [AUTH]
Xem trước phần thưởng theo level.

### 10.18. `GET /gamification/shop/items/` [AUTH]
Danh sách vật phẩm cửa hàng.

### 10.19. `POST /gamification/shop/purchase/` [AUTH]
Mua vật phẩm tại cửa hàng.

| Field | Type | Required | Description |
|---|---|---|---|
| `item_id` | uuid | [x] | ID vật phẩm |
| `lang` | string | [x] | Ngôn ngữ ví coin |
| `payment_source` | string | [x] | `paid` / `free` / `shop` |

---

## 11. Notifications — Thông báo

**Prefix:** `/api/v1/notifications/`

### 11.1. `GET /notifications/` [AUTH]
Danh sách thông báo (paginated).

### 11.2. `GET /notifications/unread/` [AUTH]
Thông báo chưa đọc.

### 11.3. `POST /notifications/mark-read/` [AUTH]
Đánh dấu đã đọc.

| Field | Type | Required | Description |
|---|---|---|---|
| `ids` | uuid[] | — | Danh sách ID (trống = đánh dấu tất cả) |

### 11.4. `GET /notifications/count/` [AUTH]
Số lượng thông báo chưa đọc.

---

## 12. Reports — Báo lỗi & Hỗ trợ

**Prefix:** `/api/v1/reports/`

### 12.1. `POST /reports/`
Báo lỗi nội dung (hỗ trợ Guest qua `X-Guest-ID`).

| Field | Type | Required | Description |
|---|---|---|---|
| `report_type` | string | [x] | image / translation / pinyin / example / exam_question / audio / other |
| `content_type` | string | [x] | zh_word / en_word / zh_example / en_example / exam_question / exam_option |
| `object_id` | string | [x] | ID đối tượng bị báo cáo |
| `reason` | string | — | Mô tả chi tiết |
| `suggested_correction` | string | — | Gợi ý sửa |

### 12.2. `POST /reports/features/`
Gửi đề xuất tính năng mới.

### 12.3. `GET/POST /reports/support/`
Yêu cầu hỗ trợ (CRUD).

### 12.4. `GET/PUT /reports/support/{pk}/` [AUTH]
Chi tiết ticket hỗ trợ (bao gồm comments).

### 12.5. `POST /reports/support/verify/`
Xác minh ticket của Guest (qua email).

### 12.6. `POST /reports/support/verify-bulk/`
Xác minh nhiều tickets của Guest.

---

## 13. XiaoYue Chat — AI Tutor

**Prefix:** `/api/v1/xiaoyue-chat/`

### 13.1. `POST /xiaoyue-chat/persona/` [AUTH]
Tạo AI Persona mới (trừ coin).

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_name` | string | [x] | Tên AI tutor |
| `personality_type` | string | [x] | cold / cheerful / strict / gentle |
| `context_setting` | string | [x] | wuxia / modern / academic |
| `learning_language` | string | [x] | zh / en |
| `user_level` | string | [x] | Trình độ |

### 13.2. `GET /xiaoyue-chat/persona/` [AUTH]
Lấy persona hiện tại.

### 13.3. `GET /xiaoyue-chat/personas/` [AUTH]
Danh sách tất cả personas của user.

### 13.4. `POST /xiaoyue-chat/send/` [AUTH]
Gửi tin nhắn tới AI tutor (trừ coin, streaming response qua WebSocket).

| Field | Type | Required | Description |
|---|---|---|---|
| `persona_id` | uuid | [x] | ID persona |
| `message` | string | [x] | Nội dung tin nhắn |

### 13.5. `POST /xiaoyue-chat/sulking/` [AUTH]
Trigger trạng thái "giận dỗi" (AI ngưng trả lời vui vẻ).

### 13.6. `POST /xiaoyue-chat/clear/` [AUTH]
Xóa lịch sử chat của persona.

### 13.7. `GET /xiaoyue-chat/history/` [AUTH]
Lịch sử chat (paginated).

| Param | Type | Required | Description |
|---|---|---|---|
| `persona_id` | uuid | [x] | |
| `page` | int | — | |

---

## 14. Community — Cộng đồng

**Prefix:** `/api/v1/community/`

### Word Comments

### 14.1. `GET/POST /community/word-comments/` [AUTH]
Lấy/Tạo bình luận trên từ vựng.

| Param (GET) | Type | Required | Description |
|---|---|---|---|
| `word_id` | uuid | [x] | ID từ vựng |
| `lang` | string | [x] | zh / en |

### 14.2. `DELETE /community/word-comments/{pk}/` [AUTH]
Xóa bình luận của mình.

### 14.3. `POST /community/word-comments/{pk}/vote/` [AUTH]
Upvote/Downvote bình luận.

| Field | Type | Required | Description |
|---|---|---|---|
| `vote` | int | [x] | `1` (upvote) hoặc `-1` (downvote) |

### Forum Posts

### 14.4. `GET /community/posts/`
Danh sách bài đăng (paginated, sorted by pinned + newest).

| Param | Type | Required | Description |
|---|---|---|---|
| `lang` | string | — | Lọc theo ngôn ngữ |

### 14.5. `POST /community/posts/` [AUTH]
Tạo bài đăng mới (hỗ trợ 1 ảnh upload).

### 14.6. `GET /community/posts/{pk}/`
Chi tiết bài đăng.

### 14.7. `PUT/DELETE /community/posts/{pk}/` [AUTH]
Sửa/Xóa bài đăng (chỉ tác giả).

### 14.8. `POST /community/posts/{pk}/like/` [AUTH]
Like/Unlike bài.

### 14.9. `POST /community/posts/{pk}/bookmark/` [AUTH]
Bookmark/Unbookmark bài.

### 14.10. `GET/POST /community/posts/{post_pk}/comments/` [AUTH]
Bình luận trên bài đăng.

### 14.11. `DELETE /community/comments/{pk}/` [AUTH]
Xóa bình luận.

### 14.12. `POST /community/comments/{pk}/like/` [AUTH]
Like bình luận.

### Reports & Appeals

### 14.13. `POST /community/report/` [AUTH]
Báo cáo nội dung vi phạm.

### 14.14. `GET/POST /community/appeals/` [AUTH]
Khiếu nại khi bị ẩn bài.

### Profile Management

### 14.15. `GET /community/me/posts/` [AUTH]
### 14.16. `GET /community/me/comments/` [AUTH]
### 14.17. `GET /community/me/likes/` [AUTH]
### 14.18. `GET /community/me/bookmarks/` [AUTH]
### 14.19. `GET /community/me/hidden/` [AUTH]

---

## 15. Leaderboard — Bảng xếp hạng

**Prefix:** `/api/v1/leaderboard/`

### 15.1. `GET /leaderboard/`
Bảng xếp hạng (snapshot 4h/lần bởi Celery).

| Param | Type | Required | Description |
|---|---|---|---|
| `board_type` | string | [x] | coin_paid / coin_free / total_likes / weekly_words / max_streak |
| `lang` | string | [x] | zh / en |

**Response:** `200 OK` — Top N ranked entries with username, avatar, score.

---

## 16. WebSocket Gateway

**URL:** `wss://cnendict.xyz/ws/notifications/`

### Connection
```
wss://domain/ws/notifications/?token={ws_token}
```

### Message Types (Server → Client)
```json
{
  "type": "score_complete",
  "payload": {
    "assessment_id": "uuid",
    "score": 85.5,
    "result_data": { ... }
  }
}
```

| Type | Description |
|---|---|
| `score_complete` | Chấm điểm phát âm hoàn tất |
| `score_failed` | Chấm điểm thất bại |
| `image_ready` | Hình ảnh AI đã sẵn sàng |
| `pdf_complete` | PDF xuất xong |
| `pdf_failed` | PDF xuất thất bại |
| `chat_stream` | Token streaming từ AI chat |
| `notification` | Thông báo chung |

---

## 17. Microservice APIs (Internal)

> Các API nội bộ này chỉ được gọi từ Celery workers qua Docker internal DNS.

### 17.1. AI English Service — `:8000`
`POST http://ai-service-en:8000/api/v1/score` — ONNX FP16 + Whisper ASR

### 17.2. AI Chinese Service — `:8001`
`POST http://ai-service-zh:8001/api/v1/score` — Faster-Whisper + custom scoring

### 17.3. TTS Service — `:8002`
`POST http://tts-service:8002/api/v1/tts` — Edge-TTS + GCS cache

### 17.4. Image Service — `:8003`
`POST http://image-service:8003/api/v1/generate` — Imagen 4.0 + GCS upload

### 17.5. PDF Service — `:8082`
`POST http://pdf-service:8082/api/v1/render` — ReportLab + Noto Sans CJK

---

## Ghi chú

- [AUTH] = Yêu cầu Authentication (JWT cookie)
- Tất cả UUID sử dụng format RFC 4122 v4
- Pagination mặc định: `page_size=20`, tối đa 100
- File upload tối đa: 20MB (Nginx `client_max_body_size`)
