// static/dashboard/js/tokenManager.js

(function(window, document) {
    // 아주 단순한 구현:
    // 1) meta[name="api-jwt"] 에서 토큰을 읽어오고
    // 2) getValidAccessToken() 으로 그대로 반환만 해준다.

    async function getValidAccessToken() {
        try {
            const meta = document.querySelector('meta[name="api-jwt"]');
            if (!meta) return '';
            return meta.content || '';
        } catch (e) {
            console.warn('[TokenManager] 읽기 실패:', e);
            return '';
        }
    }

    window.TokenManager = {
        getValidAccessToken,
    };
})(window, document);