<div dir="rtl">

# 🎬 وكيل المحتوى الذكي — AI Video Agent

وكيل ذكاء اصطناعي يكتب السيناريو، يولّد الصور، يسجّل التعليق الصوتي، يركّب
الفيديو العمودي (9:16)، ثم **ينشره على تيك توك** عبر Content Posting API الرسمي —
كل ذلك من لوحة تحكم عربية واحدة أو من سطر الأوامر.

> يعمل **فورًا بدون أي مفتاح API** بفضل الوضع المحلي (كاتب قوالب + رسم توليدي بـ Pillow + تركيب بـ FFmpeg)،
> وتزداد الجودة كثيرًا عند إضافة مفاتيح OpenAI / Gemini / ElevenLabs / Replicate.

---

## ✨ المميزات

| | |
|---|---|
| 🧠 **كتابة سيناريو** | خطاف (Hook) + مشاهد + نص على الشاشة + وصف للصورة + كابشن وهاشتاقات |
| 🖼️ **توليد الصور** | OpenAI gpt-image / Gemini / Replicate (FLUX)، أو رسم محلي توليدي بدون إنترنت |
| 🗣️ **تعليق صوتي** | ElevenLabs (عربي ممتاز) أو OpenAI TTS، مع توقيت تلقائي للمشاهد |
| 🎞️ **تركيب الفيديو** | 1080×1920، تأثير Ken Burns، تلاشٍ بين المشاهد، شريط تقدّم، علامة مائية |
| 🔤 **دعم عربي حقيقي** | تشكيل الحروف (reshaping) وترتيب RTL صحيح داخل الصور — خطوط مرفقة |
| 🎵 **موسيقى خلفية** | ملفاتك من `assets/music/` أو خلفية هارمونية مُولَّدة بـ FFmpeg |
| 🖼️ **ألبوم صور** | وضع Carousel (حتى 35 صورة) عبر `/v2/post/publish/content/init/` |
| 🎵 **نشر على تيك توك** | OAuth 2.0 + Direct Post أو Inbox (مسودة)، رفع مجزّأ (chunked) أو PULL_FROM_URL |
| ⏰ **جدولة** | جدوِل النشر لوقت لاحق، ومُجدوِل خلفي ينشر تلقائيًا |
| 🧪 **وضع محاكاة** | جرّب المسار كاملًا بدون حساب مطوّر — يسجّل المنشور محليًا |

---

## 🚀 التشغيل السريع

</div>

```bash
git clone <repo-url> && cd ai-video-agent

make install          # ينشئ .venv ويثبّت كل شيء وينسخ .env
make run              # http://localhost:8000
```

<div dir="rtl">

أو يدويًا:

</div>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli serve          # لوحة التحكم على http://localhost:8000
```

<div dir="rtl">

> **FFmpeg**: لا تحتاج تثبيته يدويًا — الحزمة `imageio-ffmpeg` تجلب نسخة جاهزة.
> إن كان لديك `ffmpeg` في الـ PATH فسيُستخدم تلقائيًا.

### أول فيديو من سطر الأوامر

</div>

```bash
python -m app.cli create --topic "٣ عادات صباحية تضاعف تركيزك" --scenes 4 --seconds 24
python -m app.cli create --topic "AI tools for students" --language en --style anime --publish
python -m app.cli list
python -m app.cli providers
```

---

<div dir="rtl">

## ⚙️ الإعداد (`.env`)

انسخ `.env.example` إلى `.env`. **كل المفاتيح اختيارية** — ما ينقص يُستبدل بالوضع المحلي.

### اختيار المزوّد

</div>

```env
TEXT_PROVIDER=auto      # auto | openai | gemini | openrouter | local
IMAGE_PROVIDER=auto     # auto | openai | gemini | replicate | local
TTS_PROVIDER=auto       # auto | elevenlabs | openai | local
```

<div dir="rtl">

`auto` يختار أول مزوّد لديه مفتاح، وإلا يسقط إلى `local`. وإذا فشل نداء مزوّد
أثناء التنفيذ (خطأ شبكة، حصة منتهية…) يكمل الوكيل محليًا ويسجّل تحذيرًا بدل أن يفشل.

### المفاتيح

</div>

```env
OPENAI_API_KEY=sk-...            # نص + صور + صوت
GEMINI_API_KEY=...               # نص + صور
ELEVENLABS_API_KEY=...           # أفضل صوت عربي
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
REPLICATE_API_TOKEN=...          # FLUX وغيره
```

---

<div dir="rtl">

## 🎵 ربط تيك توك

### ١. أنشئ تطبيقًا
من [developers.tiktok.com](https://developers.tiktok.com/) → أنشئ تطبيقًا → أضف منتج **Content Posting API**
→ اطلب الصلاحيات: `user.info.basic`, `video.publish`, `video.upload`.

### ٢. سجّل عنوان الاستدعاء
يجب أن يطابق `TIKTOK_REDIRECT_URI` تمامًا ما سجّلته في لوحة المطوّر:

</div>

```env
TIKTOK_CLIENT_KEY=aw...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=https://your-domain.com/api/tiktok/callback
PUBLIC_BASE_URL=https://your-domain.com
TIKTOK_MODE=live                 # mock = محاكاة آمنة (الافتراضي)
TIKTOK_UPLOAD_SOURCE=FILE_UPLOAD # أو PULL_FROM_URL (يتطلب توثيق نطاقك)
TIKTOK_POST_TARGET=DIRECT_POST   # أو INBOX لإرسالها كمسودة
TIKTOK_PRIVACY_LEVEL=SELF_ONLY
```

<div dir="rtl">

### ٣. اربط الحساب
من لوحة التحكم اضغط **«ربط حساب تيك توك»** (أو افتح `/api/tiktok/auth`) وأكمل تسجيل الدخول.

### ⚠️ ملاحظات مهمة من وثائق تيك توك
- **التطبيقات غير المُدقَّقة (unaudited)** تُجبَر منشوراتها على الوضع الخاص فقط، حتى تجتاز المراجعة.
- `PULL_FROM_URL` يتطلب **توثيق ملكية النطاق** في لوحة المطوّر — لذلك الافتراضي هنا `FILE_UPLOAD` (يعمل حتى من localhost).
- **ألبومات الصور** لا تدعم إلا `PULL_FROM_URL`، أي تحتاج `PUBLIC_BASE_URL` عامًا وموثّقًا.
- حدود المعدّل: 6 طلبات `init` في الدقيقة لكل توكن مستخدم.
- يجب أن يوافق المستخدم على النشر، ويُستحسن الإفصاح عن أن المحتوى مُولَّد بالذكاء الاصطناعي (AIGC).

### جرّب بدون حساب مطوّر
اترك `TIKTOK_MODE=mock`، واضغط **«إنشاء حساب تجريبي»** في اللوحة. سيُسجَّل كل «منشور»
كملف JSON داخل `data/mock_posts/` بنفس بنية طلب الـ API الحقيقي.

---

## 🧱 بنية المشروع

</div>

```
app/
├── main.py              # تطبيق FastAPI + تقديم الوسائط + دورة الحياة
├── cli.py               # أوامر: create / publish / list / providers / serve
├── config.py            # إعدادات pydantic-settings من .env
├── schemas.py           # نماذج البيانات (Job, Scene, ContentPlan, Account…)
├── storage.py           # تخزين SQLite بسيط وآمن للخيوط
├── agent/
│   ├── prompts.py       # تعليمات كاتب السيناريو
│   ├── pipeline.py      # المسار: سيناريو ➜ صور ➜ صوت ➜ فيديو
│   ├── publisher.py     # تسليم العمل إلى تيك توك
│   └── scheduler.py     # عامل خلفي ينشر المجدول
├── providers/           # طبقة المزوّدين القابلة للتبديل
│   ├── base.py registry.py local.py
│   └── openai.py gemini.py elevenlabs.py replicate.py
├── media/
│   ├── ffmpeg.py        # غلاف FFmpeg (مقاطع، صوت، دمج، مصغّرات)
│   ├── imagekit.py      # خلفيات توليدية + طبقات النصوص
│   └── textkit.py       # تشكيل عربي + RTL + ضبط تلقائي للمقاس
├── routers/             # jobs / tiktok / system
└── web/                 # لوحة تحكم عربية (HTML + CSS + JS بدون أدوات بناء)
assets/fonts/            # خطوط Cairo و Noto Sans Arabic (رخصة OFL)
data/                    # قاعدة البيانات والمخرجات (غير مُتتبَّعة في Git)
```

---

<div dir="rtl">

## 🔌 واجهة REST

التوثيق التفاعلي الكامل على `/docs`.

</div>

| Method | Endpoint | الوظيفة |
|---|---|---|
| `POST` | `/api/jobs` | إنشاء محتوى جديد (يبدأ التنفيذ فورًا) |
| `GET` | `/api/jobs` | قائمة الأعمال |
| `GET` | `/api/jobs/{id}` | تفاصيل عمل + تقدّم + سجل |
| `POST` | `/api/jobs/{id}/retry` | إعادة المحاولة |
| `GET` | `/api/jobs/{id}/download` | تنزيل MP4 |
| `DELETE` | `/api/jobs/{id}` | حذف العمل وملفاته |
| `GET` | `/api/tiktok/auth` → `/callback` | ربط حساب عبر OAuth |
| `GET` | `/api/tiktok/status` · `/accounts` | حالة التكامل والحسابات |
| `POST` | `/api/tiktok/publish` | نشر عمل جاهز |
| `POST` | `/api/tiktok/schedule` | جدولة النشر |
| `GET` | `/api/providers` · `/api/health` | حالة المزوّدين والنظام |

<div dir="rtl">

مثال:

</div>

```bash
curl -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' -d '{
  "topic": "كيف تبدأ مشروعك الأول",
  "kind": "video", "language": "ar", "style": "cinematic",
  "scene_count": 5, "seconds": 30, "voiceover": true, "auto_publish": false
}'
```

---

<div dir="rtl">

## 🧪 الاختبارات

</div>

```bash
make test        # 27 اختبارًا: التشكيل العربي، المسار الكامل، تجزئة الرفع، واجهة REST
```

<div dir="rtl">

الاختبارات تنتج فيديو MP4 حقيقيًا بالكامل دون أي اتصال بالإنترنت.

---

## 📝 حدود وملاحظات

- الوضع المحلي للصوت يُنتج **صمتًا موقوتًا** (لا يوجد محرّك نطق مفتوح مثبّت)، لذا أضف مفتاح ElevenLabs أو OpenAI للحصول على صوت فعلي.
- الوضع المحلي للصور يرسم خلفيات تجريدية جميلة لكنها ليست صورًا واقعية — استخدم مزوّدًا حقيقيًا للصور الفوتوغرافية.
- الموسيقى المُولَّدة بسيطة ومقصودة كخلفية هادئة فقط؛ ضع ملفاتك في `assets/music/` لنتيجة أفضل.
- لا تضع `.env` أو مجلد `data/` في Git (مستثناة مسبقًا في `.gitignore`).
- التزم بـ [شروط منصة تيك توك](https://developers.tiktok.com/doc/content-sharing-guidelines) وبقواعد الإفصاح عن المحتوى المُولَّد بالذكاء الاصطناعي.

</div>

---

## English summary

**AI Video Agent** turns a one-line topic into a finished 9:16 TikTok video (or photo
carousel) and publishes it through TikTok's official Content Posting API.

- **Pipeline**: script → scene images → voiceover → Ken-Burns video assembly → caption + hashtags → publish.
- **Pluggable providers**: OpenAI, Gemini, OpenRouter, ElevenLabs, Replicate — each capability falls back to a fully offline `local` provider, so the project runs with **zero API keys**.
- **Real Arabic support**: `arabic-reshaper` + `python-bidi` + bundled OFL fonts, because Pillow ships without a HarfBuzz shaper.
- **TikTok**: OAuth 2.0, `video/init` (FILE_UPLOAD with correct chunking, or PULL_FROM_URL), `content/init` for photos, inbox drafts, and `status/fetch` polling — plus a mock mode that records posts locally.
- **Interfaces**: Arabic RTL dashboard, documented REST API (`/docs`), and a CLI for cron automation.

```bash
make install && make run       # dashboard on http://localhost:8000
make test                      # offline end-to-end test suite
```

MIT licensed. Bundled fonts are SIL OFL 1.1 — see `assets/fonts/README.md`.
