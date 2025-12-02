(function() {
    try {
        // 현재 경로(끝 슬래시 제거하되, 루트는 "/"로 유지)
        var raw = window.location.pathname;
        var path = raw.replace(/\/+$/, '');
        if (path === '') path = '/';

        // 대시보드 베이스("/dashboard" 등)와 tail 구하기
        var parts = path.split('/').filter(Boolean); // ["dashboard"] or ["dashboard","reports",...]
        var base = parts.length > 0 ? '/' + parts[0] : '/';
        var tail = path.slice(base.length) || '/'; // "/", "/reports", "/reports/123" ...

        // 사이드바 메뉴들
        var links = document.querySelectorAll('.sidebar .menu-item');
        links.forEach(function(a) {
            var href = a.getAttribute('href');
            if (!href) return;

            // 절대 경로로 변환
            var url;
            try {
                url = new URL(href, window.location.origin);
            } catch {
                return;
            }

            // 링크 경로(끝 슬래시 제거하되, 루트는 "/" 유지)
            var hrefPathRaw = url.pathname;
            var hrefPath = hrefPathRaw.replace(/\/+$/, '');
            if (hrefPath === '') hrefPath = '/';

            var hrefParts = hrefPath.split('/').filter(Boolean); // ["dashboard"] or ["dashboard","reports"]
            if (hrefParts.length === 0) return;

            var hrefBase = '/' + hrefParts[0]; // "/dashboard"
            var hrefTail = hrefPath.slice(hrefBase.length) || '/'; // "/", "/reports"

            // 같은 앱의 메뉴만 비교
            if (hrefBase !== base) return;

            // 매칭 규칙
            // 1) 홈 메뉴: hrefTail === "/" 이고 현재 tail도 "/"이면 active
            // 2) 일반 메뉴: hrefTail과 tail이 완전 일치하거나, tail이 해당 섹션 하위 경로로 시작하면 active
            var isHome = hrefTail === '/' && tail === '/';
            var isExact = hrefTail !== '/' && tail === hrefTail;
            var isSection = hrefTail !== '/' && tail.startsWith(hrefTail + '/');

            if (isHome || isExact || isSection) {
                a.classList.add('active');
            }
        });
    } catch (e) {
        console.warn('[sidebar-active] failed:', e);
    }
})();
