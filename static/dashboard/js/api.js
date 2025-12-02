// 공용 axios 인스턴스 (옵셔널 체이닝/널 병합 미사용 버전)
// 팀 규칙: 로컬 기본 API
var API_BASE = 'https://dramaturgic-moneyed-cecelia.ngrok-free.dev/api';

var api = axios.create({
    baseURL: API_BASE,
    withCredentials: true, // refresh-cookie 등 쿠키 전송
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
});

// csrftoken 쿠키 읽기 (구형 호환)
function getCookie(name) {
    var cookieStr = document.cookie || '';
    if (!cookieStr) return '';
    var cookies = cookieStr.split('; ');
    for (var i = 0; i < cookies.length; i++) {
        var parts = cookies[i].split('=');
        var key = parts[0];
        if (key === name) {
            return decodeURIComponent(parts.slice(1).join('='));
        }
    }
    return '';
}

// 요청 인터셉터: CSRF 자동 부착
api.interceptors.request.use(function(cfg) {
    var csrf = getCookie('csrftoken');
    if (csrf) {
        if (!cfg.headers) cfg.headers = {};
        cfg.headers['X-CSRFToken'] = csrf;
    }
    return cfg;
});

// 응답 인터셉터: 401/403/419 표준 처리
api.interceptors.response.use(
    function(res) {
        return res;
    },
    function(err) {
        // 상태 코드 안전 추출 (옵셔널 체이닝 미사용)
        var status = null;
        if (err && err.response && typeof err.response.status !== 'undefined') {
            status = err.response.status;
        }

        // 401: Access 만료 → refresh-cookie로 재발급 시도 후 재요청
        if (status === 401) {
            return axios
                .post(API_BASE + '/token/refresh-cookie/', null, {
                    withCredentials: true,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCookie('csrftoken'),
                    },
                })
                .then(function() {
                    if (err && err.config) {
                        // 무한 루프 방지용 플래그(필요 시 사용)
                        err.config._retried = true;
                        return api.request(err.config);
                    }
                    return Promise.reject(err);
                })
                .catch(function() {
                    alert('세션이 만료되었습니다. 다시 로그인해주세요.');
                    window.location.href = '/accounts/login/';
                    return Promise.reject(err);
                });
        }

        // 403: 권한 없음
        if (status === 403) {
            alert('권한이 없습니다.');
        }

        // 419: CSRF 실패(백엔드에서 해당 코드를 쓴다면)
        if (status === 419) {
            alert('보안 토큰이 만료되었습니다. 다시 시도해주세요.');
        }

        return Promise.reject(err);
    }
);

// 전역 노출
window.API_BASE = API_BASE;
window.api = api;