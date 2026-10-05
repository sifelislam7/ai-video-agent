/* AI Video Agent — dashboard logic (vanilla JS, no build step). */

const $ = (id) => document.getElementById(id);
const api = async (path, options = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.message || `HTTP ${res.status}`);
  return body;
};

let toastTimer;
function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show${isError ? " err" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 4200);
}

const STATUS_LABEL = {
  queued: "في الانتظار", running: "قيد الإنتاج", ready: "جاهز",
  publishing: "جارٍ النشر", published: "تم النشر", failed: "فشل",
  scheduled: "مجدول",
};
const PROVIDER_LABEL = { text: "النص", image: "الصور", tts: "الصوت" };

/* ----------------------------------------------------------- status pills */
async function loadStatus() {
  try {
    const data = await api("/api/providers");
    const pills = [];
    for (const kind of ["text", "image", "tts"]) {
      const sel = data[kind].selected;
      pills.push(
        `<span class="pill ${sel === "local" ? "warn" : "ok"}">${PROVIDER_LABEL[kind]}: <b>${sel}</b></span>`
      );
    }
    const live = data.tiktok.mode === "live";
    pills.push(
      `<span class="pill ${live ? "ok" : "warn"}">تيك توك: <b>${live ? "مباشر" : "محاكاة"}</b></span>`
    );
    $("statusPills").innerHTML = pills.join("");
    $("composerHint").textContent =
      data.text.selected === "local"
        ? "لا يوجد مفتاح API — يعمل الوكيل بالوضع المحلي (كاتب قوالب + رسم توليدي). أضف مفتاحًا في .env لجودة أعلى."
        : `الكتابة عبر ${data.text.selected} · الصور عبر ${data.image.selected} · الصوت عبر ${data.tts.selected}`;
  } catch (err) {
    $("statusPills").innerHTML = `<span class="pill warn">تعذر جلب الحالة</span>`;
  }
}

/* -------------------------------------------------------------- accounts */
async function loadAccounts() {
  try {
    const [status, accounts] = await Promise.all([
      api("/api/tiktok/status"),
      api("/api/tiktok/accounts"),
    ]);
    const list = accounts.items || [];
    $("accounts").innerHTML = list.length
      ? list
          .map(
            (a) => `<div class="account">
        <div class="av">${a.mode === "live" ? "🎵" : "🧪"}</div>
        <div><b>${a.display_name || a.id}</b>
          <small>${a.mode === "live" ? "متصل بتيك توك" : "حساب محاكاة"} · ${a.id}</small></div>
        <button class="ghost small" data-del-account="${a.id}">حذف</button>
      </div>`
          )
          .join("")
      : `<p class="hint">لا توجد حسابات مرتبطة بعد.</p>`;

    $("tiktokHint").innerHTML = status.configured
      ? `الوضع: <b>${status.mode === "live" ? "نشر حقيقي" : "محاكاة"}</b> · redirect_uri: <code>${status.redirect_uri}</code>`
      : `لم تتم تهيئة تيك توك. أضف <code>TIKTOK_CLIENT_KEY</code> و <code>TIKTOK_CLIENT_SECRET</code> في ملف <code>.env</code> ثم أعد التشغيل. يمكنك الآن استخدام حساب المحاكاة لتجربة كامل المسار.`;
    $("connectBtn").disabled = !status.configured;
  } catch (err) {
    $("tiktokHint").textContent = err.message;
  }
}

/* ------------------------------------------------------------------ jobs */
function mediaBlock(job) {
  const r = job.result;
  if (!r) return `<div class="thumb">…</div>`;
  if (r.video_url) {
    return `<div class="thumb"><video src="${r.video_url}" poster="${r.thumbnail_url || ""}" controls playsinline preload="metadata"></video></div>`;
  }
  if (r.image_urls && r.image_urls.length) {
    return `<div class="thumb"><img src="${r.image_urls[0]}" alt="" /></div>`;
  }
  return `<div class="thumb">بدون معاينة</div>`;
}

function jobCard(job) {
  const r = job.result || {};
  const plan = r.plan || {};
  const status = job.status;
  const pub = r.publish || {};
  const canPublish = ["ready", "scheduled", "published", "publishing"].includes(status) && (r.video_url || (r.image_urls || []).length);
  const logs = (job.logs || []).slice(-6).map(
    (l) => `<div class="${l.level}">· ${l.message}</div>`
  ).join("");

  return `<article class="job" data-id="${job.id}">
    ${mediaBlock(job)}
    <div>
      <div class="meta" style="justify-content:space-between">
        <span class="badge ${status}">${STATUS_LABEL[status] || status}</span>
        <span>${new Date(job.created_at).toLocaleString("ar")}</span>
      </div>
      <h3>${plan.title || job.request.topic}</h3>
      <div class="meta">
        <span>${job.request.kind === "photo" ? "ألبوم صور" : "فيديو"}</span>
        <span>${(plan.scenes || []).length || job.request.scene_count} مشاهد</span>
        ${r.duration ? `<span>${r.duration}ث</span>` : ""}
        ${r.providers ? `<span>${Object.values(r.providers).join(" · ")}</span>` : ""}
      </div>
      ${status === "running" || status === "queued"
        ? `<div class="bar"><i style="width:${job.progress}%"></i></div><div class="meta">${job.step || ""} — ${job.progress}%</div>`
        : ""}
      ${plan.caption ? `<div class="caption">${plan.caption}${(plan.hashtags || []).length ? "\n" + plan.hashtags.map((t) => "#" + t).join(" ") : ""}</div>` : ""}
      ${job.error ? `<div class="caption" style="color:#ff9aae">${job.error}</div>` : ""}
      ${pub.publish_id ? `<div class="meta">🎵 ${pub.status} · <code>${pub.publish_id}</code> (${pub.mode})</div>` : ""}
      ${job.scheduled_at && status === "scheduled" ? `<div class="meta">⏰ مجدول: ${new Date(job.scheduled_at).toLocaleString("ar")}</div>` : ""}
      ${(r.image_urls || []).length > 1 && !r.video_url
        ? `<div class="gallery">${r.image_urls.map((u) => `<img src="${u}" alt="" />`).join("")}</div>` : ""}
      <div class="job-actions">
        ${canPublish ? `<button class="go" data-publish="${job.id}">نشر على تيك توك</button>` : ""}
        ${canPublish ? `<button data-schedule="${job.id}">جدولة</button>` : ""}
        ${r.video_url ? `<a href="/api/jobs/${job.id}/download" download>تنزيل MP4</a>` : ""}
        ${status === "failed" ? `<button data-retry="${job.id}">إعادة المحاولة</button>` : ""}
        <button class="danger" data-delete="${job.id}">حذف</button>
      </div>
      ${logs ? `<div class="logs">${logs}</div>` : ""}
    </div>
  </article>`;
}

let jobsCache = [];
async function loadJobs() {
  try {
    const data = await api("/api/jobs?limit=40");
    jobsCache = data.items || [];
    $("jobs").innerHTML = jobsCache.map(jobCard).join("");
    $("emptyState").style.display = jobsCache.length ? "none" : "block";
  } catch (err) {
    toast(err.message, true);
  }
}

/* --------------------------------------------------------------- actions */
async function createJob() {
  const topic = $("topic").value.trim();
  if (topic.length < 3) return toast("اكتب موضوعًا أولًا 🙂", true);

  const scheduleRaw = $("scheduleAt").value;
  const payload = {
    topic,
    kind: $("kind").value,
    language: $("language").value,
    style: $("style").value,
    scene_count: Number($("sceneCount").value),
    seconds: Number($("seconds").value),
    voiceover: $("voiceover").checked,
    captions: $("captions").checked,
    music: $("music").checked,
    audience: $("audience").value.trim(),
    extra_instructions: $("extra").value.trim(),
    auto_publish: $("autoPublish").checked,
    privacy_level: $("privacy").value,
    schedule_at: scheduleRaw ? new Date(scheduleRaw).toISOString() : null,
  };

  $("createBtn").disabled = true;
  $("createBtn").textContent = "⏳ جارٍ الإنتاج…";
  try {
    await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    toast("بدأ الإنتاج — تابع التقدم في قائمة الأعمال");
    $("topic").value = "";
    await loadJobs();
  } catch (err) {
    toast(err.message, true);
  } finally {
    $("createBtn").disabled = false;
    $("createBtn").textContent = "🚀 ابدأ الإنتاج";
  }
}

async function publishJob(jobId) {
  if (!confirm("نشر هذا المحتوى على تيك توك الآن؟")) return;
  try {
    const res = await api("/api/tiktok/publish", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, privacy_level: $("privacy").value }),
    });
    toast(`تم الإرسال: ${res.status} (${res.mode})`);
    loadJobs();
  } catch (err) {
    toast(err.message, true);
  }
}

async function scheduleJob(jobId) {
  const value = prompt("وقت النشر (YYYY-MM-DD HH:MM):", new Date(Date.now() + 3600e3)
    .toISOString().slice(0, 16).replace("T", " "));
  if (!value) return;
  const when = new Date(value.replace(" ", "T"));
  if (isNaN(when)) return toast("صيغة التاريخ غير صحيحة", true);
  try {
    await api("/api/tiktok/schedule", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, publish_at: when.toISOString() }),
    });
    toast("تمت الجدولة ⏰");
    loadJobs();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ----------------------------------------------------------------- wiring */
document.addEventListener("click", async (event) => {
  const t = event.target.closest("button");
  if (!t) return;
  if (t.dataset.publish) return publishJob(t.dataset.publish);
  if (t.dataset.schedule) return scheduleJob(t.dataset.schedule);
  if (t.dataset.retry) {
    await api(`/api/jobs/${t.dataset.retry}/retry`, { method: "POST" });
    return loadJobs();
  }
  if (t.dataset.delete) {
    if (!confirm("حذف هذا العمل وملفاته؟")) return;
    await api(`/api/jobs/${t.dataset.delete}`, { method: "DELETE" });
    return loadJobs();
  }
  if (t.dataset.delAccount) {
    await api(`/api/tiktok/accounts/${t.dataset.delAccount}`, { method: "DELETE" });
    return loadAccounts();
  }
});

$("createBtn").addEventListener("click", createJob);
$("refreshBtn").addEventListener("click", () => { loadJobs(); loadStatus(); });
$("connectBtn").addEventListener("click", () => (window.location = "/api/tiktok/auth"));
$("mockBtn").addEventListener("click", async () => {
  await api("/api/tiktok/accounts/mock", { method: "POST" });
  toast("تم إنشاء حساب المحاكاة");
  loadAccounts();
});
$("sceneCount").addEventListener("input", (e) => ($("sceneCountLabel").textContent = e.target.value));
$("seconds").addEventListener("input", (e) => ($("secondsLabel").textContent = e.target.value));

/* Poll while anything is in flight. */
setInterval(() => {
  const busy = jobsCache.some((j) => ["queued", "running", "publishing"].includes(j.status));
  if (busy) loadJobs();
}, 2500);

(async function init() {
  await Promise.all([loadStatus(), loadJobs(), loadAccounts()]);
  try {
    const cfg = await api("/api/config");
    $("language").value = cfg.default_language || "ar";
    $("sceneCount").value = cfg.default_scene_count || 5;
    $("sceneCountLabel").textContent = $("sceneCount").value;
    $("seconds").value = cfg.default_video_seconds || 30;
    $("secondsLabel").textContent = $("seconds").value;
  } catch (_) {}
})();
