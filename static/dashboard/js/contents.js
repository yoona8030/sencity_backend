// static/dashboard/js/contents.js

function val(id) {
  const el = document.querySelector(id);
  return el ? el.value : '';
}

function checked(id) {
  const el = document.querySelector(id);
  return !!(el && el.checked);
}

async function createAppBanner() {
  const payload = {
    text: val('#banner-text').trim(),
    cta_url: val('#banner-cta').trim() || null,
    start_at: val('#banner-start') || null,
    end_at: val('#banner-end') || null,
    priority: Number(val('#banner-priority') || 0),
    is_active: checked('#banner-active'),
  };

  // ✅ JWT 자동부착 + 401시 자동 재발급/재시도
  const res = await window.AdminToken.authFetch('/api/contents/app-banners/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${txt}`);
  }
  return res.json();
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.querySelector('#create-and-publish');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    try {
      await createAppBanner();
      alert('생성 완료');
      location.reload();
    } catch (e) {
      alert(`생성에 실패했습니다: ${e.message}`);
    }
  });
});
