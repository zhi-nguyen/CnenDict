# XiaoYueDict - Backend

Django REST API Gateway + Celery Task Queue + Microservices

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.10-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Django-4.2+-092E20?style=flat-square&logo=django&logoColor=white" />
  <img src="https://img.shields.io/badge/DRF-3.15-A30000?style=flat-square&logo=django&logoColor=white" />
  <img src="https://img.shields.io/badge/Celery-5.x-37814A?style=flat-square&logo=celery&logoColor=white" />
  <img src="https://img.shields.io/badge/PostgreSQL-16_(pgvector)-336791?style=flat-square&logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white" />
</p>

---

## Statistics

| Metric | Value |
|---|---|
| **Django Apps** | **16** |
| Source files | ~160 files |
| Celery scheduled tasks | 6 |
| API endpoints | 16 URL namespaces |
| Docker containers (full stack) | 15 |
| Total Commits | 125 |

---

## System Architecture

```
[Client (Next.js / Mobile)]
           │
           │ HTTPS / WSS
           ▼
[ Nginx Reverse Proxy (80/443) ]
     ├── /api/core/*  ──► [ Django API Gateway (8080) ]
     │                         ├── Database: [ PostgreSQL + pgvector (5432) ]
     │                         ├── Cache: [ Redis (6379 / DB 1) ]
     │                         └── Internal Microservice Calls:
     │                                ├── [ AI English Scorer (8000) ]
     │                                └── [ AI Chinese Scorer (8001) ]
     │
     ├── /ws/*        ──► [ WebSocket Gateway (8005) ]
     │                         └── Pub/Sub: [ Redis (6379 / DB 0) ]
     │
     ├── /api/v1/tts  ──► [ TTS Service (8002) ]
     │                         └── Storage: [ Google Cloud Storage ]
     │
     ├── /api/image/* ──► [ Image Service (8003) ]
     │                         └── Storage: [ Google Cloud Storage ]
     │
     └── /static/* & /media/* (Served directly from Docker Volumes)

[ Django API Gateway ] ──► Queue Broker (Redis DB 0) ──► [ Celery Workers (5 tiers) ]
                                                               ├── queue_core: Image Gen, Translation, PDF, Leaderboard
                                                               ├── queue_paid: AI Scoring (Paid users)
                                                               ├── queue_free: AI Scoring (Free users)
                                                               ├── queue_guest: AI Scoring (Guest users)
                                                               └── queue_chat: RAG, Summarization, AI Chat

[ AI Chat Service ] ◄── Redis PubSub ──► [ Django xiaoyue_chat ] ──► Gemini 2.5 Flash
```

---

## Codebase Architecture

```
core_django/
├── core_project/                 # Django project settings
│   ├── settings.py               # Config, CORS, JWT, Celery, Cache
│   ├── urls.py                   # Root URL routing (16 API namespaces)
│   ├── authentication.py         # Cookie-based JWT auth
│   ├── celery.py                 # Celery app config
│   ├── routers.py                # UserTierRouter (queue routing)
│   ├── exceptions.py             # Custom exception handler
│   └── ws_utils.py               # WebSocket notification helper
│
├── apps/
│   ├── dictionary_zh/            # Chinese Dictionary
│   │   ├── models.py             #    ZhWord, ZhExample (HSK 1-6)
│   │   ├── views.py              #    Full-text search (jieba + trigram)
│   │   ├── tasks.py              #    AI translation (Gemini 2.5 Flash)
│   │   └── urls.py               #    /api/v1/dictionary/zh/
│   │
│   ├── dictionary_en/            # English Dictionary
│   │   ├── models.py             #    EnWord, EnDefinition, EnExample
│   │   ├── views.py              #    Full-text search + frequency ranking
│   │   └── urls.py               #    /api/v1/dictionary/en/
│   │
│   ├── assessments/              # Pronunciation Assessment
│   │   ├── models.py             #    AssessmentTask (async queue)
│   │   ├── views.py              #    Upload audio -> AI scoring
│   │   ├── tasks.py              #    Celery: proxy to AI services
│   │   └── urls.py               #    /api/v1/assessments/
│   │
│   ├── exams/                    # Exam Management
│   │   ├── models.py             #    Exam, ExamQuestion, ExamQuestionGroup
│   │   ├── views.py              #    Fetch exams, media streaming
│   │   ├── tasks.py              #    Import exam + process media
│   │   └── urls.py               #    /api/v1/exams/
│   │
│   ├── notes/                    # Notebook & PDF Export
│   │   ├── models.py             #    Notebook, NoteWord, PdfExport
│   │   ├── views.py              #    CRUD notebooks, export PDF
│   │   ├── tasks.py              #    Async PDF generation
│   │   └── urls.py               #    /api/v1/notes/
│   │
│   ├── flashcard_exercises/      # Flashcard & Writing Practice
│   │   ├── models.py             #    FlashcardExercise, UserFlashcardHistory
│   │   ├── views.py              #    AI-gen exercises (reading/listening)
│   │   ├── prompts.py            #    Gemini prompt templates
│   │   ├── tasks.py              #    Async exercise generation
│   │   └── urls.py               #    /api/v1/flashcard/
│   │
│   ├── media/                    # AI Image Orchestration
│   │   ├── models.py             #    ZhEnMapping (cross-language bridge)
│   │   ├── views.py              #    Image status + trigger generation
│   │   ├── tasks.py              #    Celery -> Image Service -> GCS
│   │   └── urls.py               #    /api/v1/media/
│   │
│   ├── subscriptions/            # Subscription & Payments
│   │   ├── models.py             #    SubscriptionPlan, UserSubscription, PaymentOrder
│   │   ├── views.py              #    Register, upgrade, downgrade, SePay webhook
│   │   ├── middleware.py         #    VolumeLimitMiddleware (bandwidth tracking)
│   │   ├── tasks.py              #    Expiry, pending orders cleanup
│   │   └── urls.py               #    /api/v1/subscriptions/
│   │
│   ├── users/                    # User Management
│   │   ├── models.py             #    CustomUser (firebase_uid, avatar)
│   │   ├── views.py              #    Firebase login, profile update
│   │   └── urls.py               #    /api/v1/users/
│   │
│   ├── gamification/             # Gamification, Coins & Shop
│   │   ├── models.py             #    UserStreak, DailyActivity, CoinWallet,
│   │   │                         #    CoinTransaction, CoinConfig, StudySession,
│   │   │                         #    CoinPurchaseOrder, ShopItem, UserInventory...
│   │   ├── views.py              #    Dashboard, streaks, coins, shop, leveling
│   │   ├── coin_service.py       #    Coin spend/earn logic
│   │   ├── leveling_service.py   #    XP & level calculation
│   │   ├── shop_service.py       #    Item purchase & inventory
│   │   ├── tasks.py              #    Daily streaks, weekly refill, coin orders
│   │   └── urls.py               #    /api/v1/gamification/
│   │
│   ├── notifications/            # Push Notifications
│   │   ├── models.py             #    Notification (with expiry)
│   │   ├── views.py              #    List, mark read, clear
│   │   └── urls.py               #    /api/v1/notifications/
│   │
│   ├── reports/                  # Reports & Support Tickets
│   │   ├── models.py             #    ContentReport, SupportRequest, FeatureReport
│   │   ├── views.py              #    Submit report, support ticket CRUD
│   │   └── urls.py               #    /api/v1/reports/
│   │
│   ├── xiaoyue_chat/             # AI Chat (XiaoYue Tutor)
│   │   ├── models.py             #    ChatPersona, ChatMessage, ChatMemory
│   │   ├── views.py              #    Persona CRUD, chat history, streaming
│   │   ├── persona_generator.py  #    Dynamic AI persona creation
│   │   ├── tasks.py              #    RAG embedding, memory summarization
│   │   └── urls.py               #    /api/v1/xiaoyue-chat/
│   │
│   ├── community/                # Community Forum
│   │   ├── models.py             #    WordComment, ForumPost, PostComment, Vote...
│   │   ├── views.py              #    Post CRUD, voting, comment threads
│   │   ├── signals.py            #    Auto coin rewards, notification triggers
│   │   ├── throttles.py          #    Community-specific rate limits
│   │   └── urls.py               #    /api/v1/community/
│   │
│   ├── leaderboard/              # Leaderboard System
│   │   ├── models.py             #    LeaderboardSnapshot, LeaderboardEntry
│   │   ├── views.py              #    Ranked lists by coin/streak/likes
│   │   ├── tasks.py              #    Periodic snapshot refresh (every 4h)
│   │   └── urls.py               #    /api/v1/leaderboard/
│   │
│   ├── core_shared/              # Shared utilities
│   │   └── throttles.py          #    Dynamic throttle scopes
│   │
│   └── ai_gateway.py             # Unified AI service proxy
│
├── manage.py
├── requirements.txt
└── Dockerfile
```

---

## API Endpoints

| Namespace | Prefix | Description |
|---|---|---|
| `dictionary_zh` | `/api/v1/dictionary/zh/` | Chinese dictionary, search, translation |
| `dictionary_en` | `/api/v1/dictionary/en/` | English dictionary, definitions |
| `assessments` | `/api/v1/assessments/` | Upload audio, pronunciation scoring |
| `exams` | `/api/v1/exams/` | Exam lists, audio streaming |
| `notes` | `/api/v1/notes/` | Notebook CRUD, PDF export |
| `flashcard` | `/api/v1/flashcard/` | AI flashcard exercises, writing practice |
| `media` | `/api/v1/media/` | Image generation, status polling |
| `subscriptions` | `/api/v1/subscriptions/` | Subscription plans, registration, payment webhook |
| `users` | `/api/v1/users/` | Firebase authentication, profile management |
| `gamification` | `/api/v1/gamification/` | Coins, shop, streaks, leveling, study sessions |
| `notifications` | `/api/v1/notifications/` | Push notification management |
| `reports` | `/api/v1/reports/` | Content reports, support tickets |
| `xiaoyue-chat` | `/api/v1/xiaoyue-chat/` | AI tutor personas, chat, memory system |
| `community` | `/api/v1/community/` | Forum posts, word comments, voting |
| `leaderboard` | `/api/v1/leaderboard/` | Ranked leaderboard snapshots |
| `admin` | `/admin/` | Django Admin panel |

---

## Celery Task Queue

### Queue Architecture (5-tier)

```
┌─────────────────────────────────────────────────────────────┐
│                   Celery Beat (Scheduler)                    │
│  - calculate_daily_streaks          (0:00 daily)            │
│  - process_expired_subscriptions    (0:30 daily)            │
│  - purge_old_pdf_exports            (hourly)                │
│  - expire_pending_payment_orders    (every 5 min)           │
│  - refresh_all_leaderboards         (every 4 hours)         │
│  - cleanup_old_leaderboard_snapshots(1:30 daily)            │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│queue_core│queue_paid│queue_free│queue_guest│queue_chat│
│          │          │          │          │          │
│- Image   │- AI Paid │- AI Free │- AI Guest│- RAG     │
│  Gen     │  Scoring │  Scoring │  Scoring │  Embed   │
│- Transla-│          │          │          │- Memory  │
│  tion    │          │          │          │  Summa-  │
│- PDF Gen │          │          │          │  rization│
│- Leader- │          │          │          │          │
│  board   │          │          │          │          │
│- Flash-  │          │          │          │          │
│  card Gen│          │          │          │          │
└──────────┘──────────┘──────────┘──────────┘──────────┘
   Worker     Worker     Worker     Worker     Worker
   (conc=2)   (conc=1)   (conc=1)   (conc=1)   (conc=2)
```

### Async Tasks

| Task | Queue | Description |
|---|---|---|
| `generate_word_image_task` | `queue_core` | Generates AI image -> GCS upload -> WS notify |
| `trigger_image_regeneration_task` | `queue_core` | Deletes old image + regenerates |
| `translate_pure_text_task` | `queue_core` | Chinese -> Vietnamese translation via Gemini AI |
| `process_audio_task` | `queue_paid/free/guest` | Proxies audio to internal AI scoring service |
| `generate_pdf_task` | `queue_core` | Renders vocabulary PDF (Noto Sans CJK fonts) |
| `import_full_exam_task` | `queue_core` | Imports exam metadata & processes audio segments |
| `calculate_daily_streaks` | `queue_core` | Calculates user learning streaks daily |
| `process_expired_subscriptions` | `queue_core` | Handles expired subscription plan downgrades |
| `refresh_all_leaderboards` | `queue_core` | Snapshots ranked leaderboards (5 board types) |
| `cleanup_old_snapshots` | `queue_core` | Removes stale leaderboard data |
| `generate_flashcard_task` | `queue_core` | AI-generates reading/listening exercises |
| `summarize_chat_memory` | `queue_chat` | Summarizes chat history for RAG retrieval |
| `embed_chat_memory` | `queue_chat` | Creates pgvector embeddings for chat recall |

---

## Authentication and Security

### Authentication Flow

```
Firebase Client SDK -> Firebase ID Token
        │
        ▼
Next.js BFF (Backend-for-Frontend)
        │ httpOnly Cookie (access_token + refresh_token)
        ▼
Django CookieJWTAuthentication
        │
        ▼
REST Framework Permission Classes
```

### Security Layers

| Layer | Implementation |
|---|---|
| **Auth Provider** | Firebase Authentication (Google, Email) |
| **Token Format** | JWT (SimpleJWT) in httpOnly Secure cookies |
| **CORS** | Explicit origins + Vercel preview regex |
| **CSRF** | Django CSRF middleware |
| **Rate Limiting** | DRF throttles: `anon=30/min`, `user=60/min` |
| **Volume Limiting** | `VolumeLimitMiddleware` - bandwidth limit per tier |
| **HSTS** | 1 year + preload + subdomains |
| **Guest Support** | `X-Guest-ID` header, IDOR protection |
| **Nginx Rate Limit** | Community image upload: 5 req/min per IP |

---

## Database Schema

### Core Models

| App | Model | Description |
|---|---|---|
| `dictionary_zh` | `ZhWord` | Chinese words (HSK level, pinyin, Han-Viet, definitions) |
| `dictionary_zh` | `ZhExample` | Chinese example sentences |
| `dictionary_en` | `EnWord` | English words (IPA, frequency rank, part of speech) |
| `dictionary_en` | `EnDefinition` | English definition details |
| `assessments` | `AssessmentTask` | Async pronunciation assessment task |
| `exams` | `Exam`, `ExamQuestion` | HSK/IELTS exam management models |
| `notes` | `Notebook`, `NoteWord` | User notebook and word mappings |
| `flashcard_exercises` | `FlashcardExercise` | AI-generated reading/listening quiz content |
| `flashcard_exercises` | `UserFlashcardHistory` | User exercise completion history |
| `media` | `ZhEnMapping` | Cross-language mapping + prompt description |
| `subscriptions` | `SubscriptionPlan` | 4 tiers: Free, Plus, Pro, Premium |
| `subscriptions` | `UserSubscription` | Active user subscriptions |
| `subscriptions` | `PaymentOrder` | SePay automated QR payment order |
| `users` | `CustomUser` | User profile extensions (Firebase UID, avatar) |
| `gamification` | `UserStreak`, `DailyActivity` | Active study streak calendar |
| `gamification` | `CoinWallet`, `CoinTransaction` | Dual-currency wallet (paid/free/shop balance) |
| `gamification` | `CoinConfig` | Admin-configurable coin costs per tier |
| `gamification` | `StudySession`, `StudySessionCard` | Flashcard study session tracking |
| `gamification` | `CoinPurchaseOrder` | Coin purchase via SePay payment |
| `xiaoyue_chat` | `ChatPersona` | AI tutor persona (personality, emotional state) |
| `xiaoyue_chat` | `ChatMessage` | Chat history with role-based messages |
| `xiaoyue_chat` | `ChatMemory` | RAG vector embeddings (pgvector) |
| `community` | `WordComment` | Per-word comment with upvote/downvote |
| `community` | `ForumPost`, `PostComment` | Community forum threads |
| `leaderboard` | `LeaderboardSnapshot` | Periodic ranking snapshots (5 board types) |
| `leaderboard` | `LeaderboardEntry` | Individual ranked entries |
| `notifications` | `Notification` | Push notification persistence with TTL |
| `reports` | `ContentReport`, `SupportRequest` | System bug reporting & customer service tickets |

### Search Optimization

- **GIN Index** on `translation_vi`, `han_viet` (Chinese dictionary search)
- **Trigram Index** (`pg_trgm`) for fuzzy search on Vietnamese definitions
- **Full-text Search Vector** on `ZhExample` and `EnExample`
- **Jieba Tokenization** for Chinese segment search indexing
- **pgvector** for chat memory RAG similarity search

---

## Integrated Microservices

| Service | Port | Stack | Description |
|---|---|---|---|
| **AI English** | `:8000` | FastAPI + ONNX | ONNX FP16 pronunciation scorer + Whisper ASR |
| **AI Chinese** | `:8001` | FastAPI + Whisper | Faster-Whisper + custom scoring algorithms |
| **TTS** | `:8002` | FastAPI | Edge-TTS neural voices + Google Cloud Storage cache |
| **Image** | `:8003` | FastAPI | Imagen 4.0 API + Google Cloud Storage upload |
| **PDF** | `:8082` | FastAPI | ReportLab engine + Noto Sans SC font loading |
| **WS Gateway** | `:8005` | FastAPI + Redis | WebSocket pub/sub notification router |
| **AI Chat** | — | Python + Gemini | Streaming AI tutor with emotional state + RAG memory |

---

## Caching Strategy

```
Request -> Nginx Cache (static) -> Django View
                                      │
                                      ▼
                               Redis Cache (L1)
                              ┌────────────────────┐
                              │ img:{lang}:{id}     │ -> Image status/URL
                              │ generating:img:...  │ -> Lock flag (5 min TTL)
                              │ dict:zh:search:...  │ -> Search results
                              │ translation:...     │ -> AI translation cache
                              │ leaderboard:...     │ -> Ranked snapshots
                              └────────────────────┘
                                      │ Cache Miss
                                      ▼
                               PostgreSQL (L2)
```

---

## Development

### Prerequisites

- **Docker** & **Docker Compose** (v2+)
- **NVIDIA GPU Drivers** + **NVIDIA Container Toolkit** (for AI services)
- **Google Cloud Service Account** (`key.json`) — for GCS, Imagen, Gemini APIs
- **Firebase Project** — for user authentication

### Getting Started

```bash
# 1. Clone the repository
git clone https://github.com/your-org/XiaoYueDict.git
cd XiaoYueDict

# 2. Create environment file from template
cp .env.example .env
# Edit .env with your actual credentials (DB password, API keys, etc.)

# 3. Place Google Cloud credentials
# Copy your service account key.json into core_django/key.json

# 4. Start all services
docker compose up -d --build

# 5. Apply database migrations
docker exec xiaoyuedict-core-django-1 python manage.py migrate

# 6. Create admin superuser
docker exec -it xiaoyuedict-core-django-1 python manage.py createsuperuser

# 7. (Optional) Seed initial data
docker exec xiaoyuedict-core-django-1 python manage.py shell < scratch/seed_db.py
```

### Common Commands

```bash
# Run Django dev server (inside Docker)
docker exec -it xiaoyuedict-core-django-1 python manage.py runserver 0.0.0.0:8080

# Apply migrations
docker exec xiaoyuedict-core-django-1 python manage.py migrate

# Create superuser
docker exec -it xiaoyuedict-core-django-1 python manage.py createsuperuser

# Monitor Celery worker logs
docker logs -f xiaoyuedict-celery-worker-core-1

# Open Django shell
docker exec -it xiaoyuedict-core-django-1 python manage.py shell

# View all running containers
docker compose ps

# Restart a specific service
docker compose restart core-django

# View real-time logs for all services
docker compose logs -f
```

### Environment Variables

```env
# Database Configuration
POSTGRES_DB=xiaoyue
POSTGRES_USER=xiaoyue
POSTGRES_PASSWORD=your_secure_password
DATABASE_URL=postgres://xiaoyue:your_secure_password@db:5432/xiaoyue

# Django Environment
DJANGO_DEBUG=True
ALLOWED_HOSTS=*
SECRET_KEY=replace-this-in-production
JWT_SECRET_KEY=replace-this-in-production

# Redis & Celery Config
REDIS_PASSWORD=your_secure_password
REDIS_URL=redis://:your_secure_password@redis:6379/0
CELERY_BROKER_URL=redis://:your_secure_password@redis:6379/0
CELERY_RESULT_BACKEND=redis://:your_secure_password@redis:6379/0
REDIS_CACHE_URL=redis://:your_secure_password@redis:6379/1

# AI Services Endpoints
AI_SERVICE_EN_URL=http://ai-service-en:8000/api/v1/score
AI_SERVICE_ZH_URL=http://ai-service-zh:8001/api/v1/score

# External Configurations
GOOGLE_APPLICATION_CREDENTIALS=/app/key.json
GS_BUCKET_NAME=your-gcs-bucket-name

# SePay Payment Configuration
SEPAY_WEBHOOK_SECRET=your_webhook_secret_here
SEPAY_BANK_CODE=YourBankCode
SEPAY_ACCOUNT_NUMBER=your_account_number
SEPAY_ACCOUNT_NAME=YOUR_FULL_NAME
SEPAY_ORDER_PREFIX=CNEN
SEPAY_PAYMENT_TIMEOUT_MINUTES=15
```

> See [`.env.example`](.env.example) for the full template.

---

## Docker Services

| Service | Image / Build | Port | Description |
|---|---|---|---|
| `nginx` | nginx:alpine | 80 | Reverse proxy & static file serving |
| `redis` | redis:alpine | — | Message broker, result backend, cache |
| `db` | pgvector/pgvector:pg16 | 5433→5432 | PostgreSQL + pgvector |
| `core-django` | ./core_django | 8080 | Django API Gateway (Gunicorn) |
| `celery-worker-core` | ./core_django | — | Core tasks: image, translation, PDF, leaderboard |
| `celery-worker-priority` | ./core_django | — | Paid-tier AI scoring |
| `celery-worker-standard` | ./core_django | — | Paid + Free AI scoring |
| `celery-worker-guest` | ./core_django | — | Guest + Free AI scoring |
| `celery-worker-chat` | ./core_django | — | AI Chat RAG & summarization |
| `celery-beat` | ./core_django | — | Periodic task scheduler |
| `ai-service-zh` | ./ai_service_zh | 8001 | Chinese pronunciation AI (GPU) |
| `ai-service-en` | ./ai_service_en | 8000 | English pronunciation AI (GPU) |
| `tts-service` | ./tts_service | 8002 | Text-to-Speech |
| `image-service` | ./image_service | 8003 | AI image generation (Imagen 4.0) |
| `pdf-service` | ./pdf_service | 8082 | PDF rendering |
| `ws-gateway` | ./ws_gateway | 8005 | WebSocket gateway |
| `ai-chat-service` | ./ai_chat_service | — | AI Chat streaming agent (Gemini) |

---

## Dependencies

```
django>=4.2                 # Web framework
djangorestframework         # REST API
djangorestframework-simplejwt # JWT auth
celery                      # Task queue
redis                       # Broker + cache
psycopg2-binary             # PostgreSQL driver
pgvector                    # Vector similarity search
gunicorn                    # WSGI server
django-cors-headers         # CORS handling
dj-database-url             # Database URL parsing
firebase-admin              # Firebase Authentication
google-genai                # Gemini AI (translation, flashcards, chat)
google-cloud-storage        # GCS object storage
google-cloud-aiplatform     # Vertex AI (Imagen)
google-generativeai         # Generative AI SDK
jieba                       # Chinese text segmentation
pyspellchecker              # Spell checking
Pillow                      # Image processing
PyJWT>=2.8                  # JWT encoding
requests                    # HTTP client
```

---

<sub>See also: [Frontend README](frontend_nextjs/README.md)</sub>
