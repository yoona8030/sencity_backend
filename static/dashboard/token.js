(function() {
    'use strict';

    function getMeta(name) {
        var el = document.querySelector('meta[name="' + name + '"]');
        return el ? el.getAttribute('content') || '' : '';
    }

    function setMeta(name, value) {
        var el = document.querySelector('meta[name="' + name + '"]');
        if (el) el.setAttribute('content', value);
    }

    function parseJwt(token) {
        if (!token) return null;
        try {
            var payload = token.split('.')[1];
            var json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
            return JSON.parse(decodeURIComponent(escape(json)));
        } catch (e) {
            return null;
        }
    }

    function secondsUntilExpiry(token) {
        var p = parseJwt(token);
        if (!p || !p.exp) return 0;
        var nowSec = Math.floor(Date.now() / 1000);
        return p.exp - nowSec;
    }

    function issueNewToken() {
        var csrf = getMeta('csrf-token');
        return fetch('/dashboard/api/issue-token/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrf },
                credentials: 'same-origin',
            })
            .then(function(res) {
                if (!res.ok) throw new Error('issue-token failed ' + res.status);
                return res.json();
            })
            .then(function(data) {
                if (!data || !data.access) throw new Error('no access in response');
                setMeta('api-jwt', data.access);
                scheduleRefresh();
                return data.access;
            });
    }

    var refreshTimer = null;

    function scheduleRefresh() {
        if (refreshTimer) {
            clearTimeout(refreshTimer);
            refreshTimer = null;
        }
        var token = getMeta('api-jwt');
        var sec = secondsUntilExpiry(token);
        if (sec <= 0) {
            issueNewToken().catch(function() {});
            return;
        }
        var refreshInMs = Math.max((sec - 60) * 1000, 5000);
        refreshTimer = setTimeout(function() {
            issueNewToken().catch(function() {});
        }, refreshInMs);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            var csrfFromMeta = getMeta('csrf-token');
            if (!csrfFromMeta) {
                console.warn('[AdminToken] csrf-token meta not found; token refresh disabled');
                // scheduleRefresh() 호출 생략
            } else {
                scheduleRefresh();
            }
        });
    } else {
        var csrfFromMeta = getMeta('csrf-token');
        if (!csrfFromMeta) {
            console.warn('[AdminToken] csrf-token meta not found; token refresh disabled');
            // scheduleRefresh() 호출 생략
        } else {
            scheduleRefresh();
        }
    }

    window.AdminToken = {
        get: function() {
            return getMeta('api-jwt');
        },
        refresh: function() {
            return issueNewToken();
        },
        authHeaders: function() {
            var t = getMeta('api-jwt');
            return t ? { Authorization: 'Bearer ' + t } : {};
        },
        authFetch: function(url, options) {
            options = options || {};
            var self = this;

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

            function withAuthAndCsrf(opts) {
                var headers = Object.assign({}, opts.headers || {}, self.authHeaders());
                var method = (opts.method || 'GET').toUpperCase();
                // Django: 안전하지 않은 메서드에는 CSRF 필요
                if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
                    headers['X-CSRFToken'] = getCookie('csrftoken') || '';
                }
                return Object.assign({}, opts, { headers, credentials: 'same-origin' });
            }

            function tryOnce() {
                return fetch(url, withAuthAndCsrf(options));
            }

            return tryOnce().then(function(res) {
                if (res.status !== 401) return res;
                return self
                    .refresh()
                    .catch(function() {})
                    .then(tryOnce);
            });
        },
    };
})();