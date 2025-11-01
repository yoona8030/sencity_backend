(function() {
    function getCookie(name) {
        let v = null;
        if (document.cookie && document.cookie !== '') {
            document.cookie
                .split(';')
                .map((s) => s.trim())
                .forEach((c) => {
                    if (c.startsWith(name + '=')) v = decodeURIComponent(c.slice(name.length + 1));
                });
        }
        return v;
    }

    async function sendBroadcastPush({ title, body, data = {}, userIds = null, user_ids = null }) {
        const titleClean = (title !== undefined && title !== null ? title : '').toString().trim();
        const bodyClean = (body !== undefined && body !== null ? body : '').toString().trim();
        if (!titleClean && !bodyClean) {
            throw new Error('제목 또는 본문 중 하나는 필요합니다.');
        }

        let normalizedUserIds = Array.isArray(userIds) ? userIds : Array.isArray(user_ids) ? user_ids : null;
        if (Array.isArray(normalizedUserIds) && normalizedUserIds.length === 0) {
            normalizedUserIds = null;
        }

        const payload = {
            title: titleClean || undefined,
            body: bodyClean || undefined,
            data,
            user_ids: normalizedUserIds,
        };

        if (!window.AdminToken || typeof window.AdminToken.authFetch !== 'function') {
            throw new Error('AdminToken이 초기화되지 않았습니다 (token.js 포함 순서 확인).');
        }

        const res = await window.AdminToken.authFetch('/api/push/broadcast/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const text = await res.text().catch(() => '');
            let msg = `HTTP ${res.status}`;
            try {
                const j = JSON.parse(text);
                if (j.detail) msg += `: ${j.detail}`;
                else if (j.error) msg += `: ${j.error}`;
            } catch {}
            throw new Error(msg);
        }

        const out = await res.json();
        if (Array.isArray(out.failure_tokens) && out.failure_tokens.length) {
            console.warn('[FCM] invalid tokens sample:', out.failure_tokens.slice(0, 3), `(+${Math.max(0, out.failure_tokens.length - 3)} more)`);
        }
        return out;
    }

    window.sendBroadcastPush = sendBroadcastPush;
})();