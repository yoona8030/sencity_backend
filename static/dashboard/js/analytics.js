/* ===== 유틸 ===== */
const $ = (id) => document.getElementById(id);
const getParam = (n) => new URL(location.href).searchParams.get(n);
const setParam = (n, v) => {
    const u = new URL(location.href);
    u.searchParams.set(n, v);
    history.replaceState(null, '', u.toString());
};
const fetchJSON = (url) =>
    fetch(url, { credentials: 'same-origin' }).then((r) => {
        if (!r.ok) throw new Error('fetch ' + r.status);
        return r.json();
    });

function fillYears(id) {
    const sel = $(id);
    const years = [2024, 2025, 2026];
    sel.innerHTML = years
        .map(function(y) {
            return '<option value="' + y + '">' + y + '</option>';
        })
        .join('');
    const q = parseInt(getParam('year') || '', 10);
    const cur = new Date().getFullYear();
    sel.value = Number.isInteger(q) && years.indexOf(q) !== -1 ? q : cur <= 2026 ? cur : 2025;
}

/* ===== 공통 ===== */
let BAR_RECTS = [],
    LINE_POINTS = [];

function niceStep(maxVal, ticks) {
    const raw = maxVal / Math.max(ticks, 1);
    const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
    const cand = [1, 2, 5].map(function(k) {
        return k * p;
    });
    let step = cand[0];
    for (let i = 0; i < cand.length; i++) {
        if (raw <= cand[i]) {
            step = cand[i];
            break;
        }
    }
    return { step: step, maxRounded: Math.ceil(maxVal / step) * step };
}

/* ===== 도넛 ===== */
function getRowLabel(p) {
    if (Array.isArray(p) && p.length > 0 && p[0] !== null && p[0] !== undefined) return String(p[0]);
    return '';
}

function getRowValue(p) {
    if (Array.isArray(p) && p.length > 1 && p[1] !== null && p[1] !== undefined) {
        const n = Number(p[1]);
        return isNaN(n) ? 0 : n;
    }
    return 0;
}

function drawDonut(canvas, pairs, legend) {
    const ctx = canvas.getContext('2d');

    const parent = canvas.parentElement;
    const pW = parent ? parent.clientWidth : 0;
    let W = canvas.clientWidth || pW || 300;
    let H = canvas.clientHeight || Math.max(Math.floor(W * 0.75), 160);

    const maxW = 340;
    W = Math.min(W, maxW);
    H = Math.min(H, Math.floor(maxW * 0.75));

    canvas.width = W;
    canvas.height = H;

    const cx = W / 2,
        cy = H / 2;
    const padding = 10;
    const minRadius = 8;
    const outer = Math.floor(Math.min(W, H) / 2 - padding);

    if (outer < minRadius) {
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#888';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '12px system-ui';
        ctx.fillText('공간이 부족합니다', cx, cy);
        if (legend) legend.innerHTML = '';
        return;
    }

    const thickTarget = Math.floor(outer * 0.38);
    const thickness = Math.max(16, Math.min(thickTarget, outer - minRadius));
    const inner = Math.max(minRadius, outer - thickness);

    const colors = ['#64b5f6', '#81c784', '#ffd54f', '#e57373', '#4db6ac', '#ba68c8', '#90a4ae'];

    const rows = Array.isArray(pairs) ? pairs.slice() : [];
    rows.sort(function(a, b) {
        return getRowLabel(a).localeCompare(getRowLabel(b));
    });

    const total = rows.reduce(function(s, p) {
        return s + getRowValue(p);
    }, 0);

    ctx.clearRect(0, 0, W, H);

    if (total <= 0) {
        ctx.beginPath();
        ctx.fillStyle = '#f1f5f9';
        ctx.arc(cx, cy, outer, 0, Math.PI * 2);
        ctx.moveTo(cx + inner, cy);
        ctx.arc(cx, cy, inner, 0, Math.PI * 2, true);
        ctx.closePath();
        ctx.fill();
        if (legend) {
            legend.innerHTML = '<div class="legend-item"><span class="legend-swatch" style="background:#f1f5f9"></span>데이터 없음</div>';
        }
        return;
    }

    let a = -Math.PI / 2;
    rows.forEach(function(p, i) {
        const v = Math.max(0, getRowValue(p));
        if (!v) return;
        const sweep = (v / total) * Math.PI * 2;
        ctx.beginPath();
        ctx.arc(cx, cy, outer, a, a + sweep);
        ctx.arc(cx, cy, inner, a + sweep, a, true);
        ctx.closePath();
        ctx.fillStyle = colors[i % colors.length];
        ctx.fill();
        a += sweep;
    });

    if (legend) {
        legend.innerHTML = rows
            .map(function(p, i) {
                const label = getRowLabel(p) || '미상';
                return (
                    '<div class="legend-item"><span class="legend-swatch" style="background:' +
                    colors[i % colors.length] +
                    '"></span>' +
                    label +
                    '</div>'
                );
            })
            .join('');
    }
}

/* ===== 가로 막대 ===== */
function drawBarHorizontal(canvas, labels, values) {
    const ctx = canvas.getContext('2d');
    const W = (canvas.width = canvas.clientWidth || 480);
    const H = (canvas.height = canvas.clientHeight || 240);

    ctx.clearRect(0, 0, W, H);

    const padL = 48,
        padR = 24,
        padT = 24,
        padB = 32;
    const plotW = W - padL - padR,
        plotH = H - padT - padB;

    const vmax = Math.max.apply(null, values.concat([0]));
    const ns = niceStep(vmax, 5);
    const xMax = Math.max(ns.maxRounded, 1);
    const xStep = ns.step;

    // 축
    ctx.strokeStyle = '#e5e7eb';
    ctx.beginPath();
    ctx.moveTo(padL, padT);
    ctx.lineTo(padL, padT + plotH);
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.stroke();

    // X눈금
    ctx.fillStyle = '#555';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let x = 0; x <= xMax; x += xStep) {
        const px = padL + (x / xMax) * plotW;
        ctx.strokeStyle = 'rgba(0,0,0,0.06)';
        ctx.beginPath();
        ctx.moveTo(px, padT);
        ctx.lineTo(px, padT + plotH);
        ctx.stroke();
        ctx.fillStyle = '#555';
        ctx.fillText(String(x), px, padT + plotH + 6);
    }

    // 막대
    const n = values.length,
        stepY = plotH / n,
        barH = stepY * 0.6;
    ctx.fillStyle = '#90caf9';
    BAR_RECTS = [];
    values.forEach(function(v, i) {
        const w = plotW * (v / xMax);
        const x = padL;
        const y = padT + i * stepY + (stepY - barH) / 2;
        ctx.fillRect(x, y, w, barH);
        BAR_RECTS.push({ x: x, y: y, w: w, h: barH, idx: i });
    });

    // 레이블(월)
    ctx.fillStyle = '#555';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    labels.forEach(function(lb, i) {
        const s = String(lb || '');
        const mm = s.slice(5, 7) || String(i + 1).padStart(2, '0');
        const ly = padT + i * stepY + stepY / 2;
        ctx.fillText(mm, padL - 6, ly);
    });
}

/* ===== 선 그래프 ===== */
function drawLineNormal(canvas, labels, values) {
    const ctx = canvas.getContext('2d');
    const W = (canvas.width = canvas.clientWidth || 480);
    const H = (canvas.height = canvas.clientHeight || 260);

    ctx.clearRect(0, 0, W, H);

    const padL = 48,
        padR = 24,
        padT = 24,
        padB = 40;
    const plotW = W - padL - padR,
        plotH = H - padT - padB;

    const vmax = Math.max.apply(null, values.concat([0]));
    const ns = niceStep(vmax, 5);
    const yMax = Math.max(ns.maxRounded, 1);
    const yStep = ns.step;

    // 격자/축
    ctx.strokeStyle = '#e5e7eb';
    ctx.beginPath();
    ctx.moveTo(padL, padT);
    ctx.lineTo(padL, padT + plotH);
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.stroke();

    // Y라벨
    ctx.fillStyle = '#555';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let y = 0; y <= yMax; y += yStep) {
        const py = padT + plotH - (y / yMax) * plotH;
        ctx.strokeStyle = 'rgba(0,0,0,0.06)';
        ctx.beginPath();
        ctx.moveTo(padL, py);
        ctx.lineTo(padL + plotW, py);
        ctx.stroke();
        ctx.fillStyle = '#555';
        ctx.fillText(String(y), padL - 6, py);
    }

    // 선
    const n = values.length,
        stepX = n > 1 ? plotW / (n - 1) : 0;
    ctx.strokeStyle = '#64b5f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    LINE_POINTS = [];
    values.forEach(function(v, i) {
        const x = padL + i * stepX;
        const y = padT + plotH - plotH * (v / yMax);
        LINE_POINTS.push({ x: x, y: y, idx: i });
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // 점
    ctx.fillStyle = '#64b5f6';
    LINE_POINTS.forEach(function(p) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
    });

    // X라벨(월)
    ctx.fillStyle = '#555';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    labels.forEach(function(lb, i) {
        const s = String(lb || '');
        const mm = s.slice(5, 7) || String(i + 1).padStart(2, '0');
        const lx = padL + i * stepX;
        ctx.fillText(mm, lx, padT + plotH + 6);
    });
}

/* ===== 데이터 로드 ===== */
let CURRENT_YEAR = new Date().getFullYear();

function computeKPI(months, counts, top) {
    const total = counts.reduce(function(s, n) {
        return s + (n || 0);
    }, 0);
    const avg = (total / 12).toFixed(1);
    let pk = -1,
        mx = -1;
    counts.forEach(function(v, i) {
        if (v > mx) {
            mx = v;
            pk = i;
        }
    });

    $('kpi-total').textContent = String(total);
    $('kpi-avg').textContent = String(avg);
    $('kpi-peak').textContent = pk >= 0 && months[pk] ? months[pk] : '-';
    $('kpi-top').textContent = typeof top === 'string' && top ? top : '-';
}

function loadAll(year) {
    CURRENT_YEAR = year;
    fetchJSON('/dashboard/api/analytics/?year=' + encodeURIComponent(year))
        .then(function(d) {
            const months = Array.isArray(d.months) ? d.months : [];
            const counts = (Array.isArray(d.counts) ? d.counts : []).map(function(n) {
                n = Number(n);
                return isNaN(n) ? 0 : n;
            });

            computeKPI(months, counts, d.top_animal || '-');
            drawBarHorizontal($('barMonthly'), months, counts);
            drawDonut($('donutAnimal'), d.by_animal_top || [], $('legend-animal'));
            drawLineNormal($('lineMonthly'), months, counts);

            renderLeafletPoints();
        })
        .catch(function(e) {
            console.error('[analytics] analytics API error:', e);
        });
}

/* ===== Leaflet 지도 ===== */
let LMAP = null,
    LAYER_POINTS = null;
let MAP_LOCKED = false;

function setMapInteractivity(enabled) {
    if (!LMAP) return;
    const fn = enabled ? 'enable' : 'disable';
    LMAP.dragging[fn]();
    LMAP.touchZoom[fn]();
    LMAP.scrollWheelZoom[fn]();
    LMAP.doubleClickZoom[fn]();
    LMAP.boxZoom[fn]();
    LMAP.keyboard[fn]();
}

function applyMapLockState() {
    setMapInteractivity(!MAP_LOCKED);
    const wrap = document.querySelector('.leaflet-wrap');
    if (wrap) wrap.classList.toggle('locked', MAP_LOCKED);
    const btn = document.getElementById('map-lock');
    if (btn) {
        btn.setAttribute('aria-pressed', MAP_LOCKED ? 'true' : 'false');
        btn.textContent = MAP_LOCKED ? '해제' : '고정';
        btn.title = MAP_LOCKED ? '지도를 해제합니다' : '지도를 고정합니다';
    }
}

function initLeafletMap() {
    if (LMAP) return;
    LMAP = L.map('leafletMap', { zoomControl: true, attributionControl: false, preferCanvas: true });
    LMAP.setView([36.4, 127.9], 7);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(LMAP);

    const southWest = L.latLng(32.5, 123.5),
        northEast = L.latLng(39.5, 132.0);
    LMAP.setMaxBounds(L.latLngBounds(southWest, northEast));

    setTimeout(function() {
        LMAP.invalidateSize();
        applyMapLockState();
    }, 0);
}

function blueColor(t) {
    const a = 0.35 + t * 0.6;
    return 'rgba(59,130,246,' + a + ')';
}

function makeCircleWithHalo(lat, lng, radius, color, tooltipHtml) {
    const halo = L.circleMarker([lat, lng], {
        radius: Math.max(radius + 4, 6),
        stroke: true,
        color: '#ffffff',
        weight: 3,
        fill: false,
        interactive: false,
    });
    const dot = L.circleMarker([lat, lng], {
        radius: Math.max(radius, 4),
        stroke: true,
        color: 'rgba(17,24,39,0.40)',
        weight: 1.5,
        fillColor: color,
        fillOpacity: 1,
    });
    dot.on('mouseover', function(e) {
        e.target.setStyle({ radius: Math.max(radius + 3, 7), weight: 3 });
    });
    dot.on('mouseout', function(e) {
        e.target.setStyle({ radius: Math.max(radius, 4), weight: 1.5 });
    });
    if (tooltipHtml)
        dot.bindTooltip(tooltipHtml, { direction: 'top', offset: L.point(0, -6), sticky: true, opacity: 0.95, className: 'map-tip' });
    return [halo, dot];
}

function firstDefined() {
    for (let i = 0; i < arguments.length; i++) {
        const v = arguments[i];
        if (v !== undefined && v !== null) return v;
    }
    return undefined;
}

async function renderLeafletPoints() {
    try {
        initLeafletMap();

        if (LAYER_POINTS) {
            LAYER_POINTS.clearLayers();
            LMAP.removeLayer(LAYER_POINTS);
        }
        LAYER_POINTS = L.layerGroup();

        const animalSel = document.getElementById('map-animal');
        const animal = animalSel && animalSel.value ? String(animalSel.value).trim() : '';
        let url = '/dashboard/api/report-points/?year=' + encodeURIComponent(CURRENT_YEAR);
        if (animal) url += '&animal=' + encodeURIComponent(animal);

        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) {
            console.warn('[analytics] report-points HTTP', res.status);
            LAYER_POINTS.addTo(LMAP);
            return;
        }
        const json = await res.json();
        let rows = Array.isArray(json) ? json : json.rows || json.points || json.data || [];
        if (!Array.isArray(rows) || rows.length === 0) {
            LAYER_POINTS.addTo(LMAP);
            return;
        }

        let cMax = 1;
        rows.forEach(function(r) {
            const c = Number(firstDefined(r.count, r.cnt, r.n, 0) || 0);
            if (c > cMax) cMax = c;
        });

        const bounds = [];
        rows.forEach(function(r) {
            let lat = firstDefined(r.lat, r.latitude, r.coord && r.coord.lat, Array.isArray(r.coords) ? r.coords[0] : undefined);
            let lng = firstDefined(r.lng, r.longitude, r.coord && r.coord.lng, Array.isArray(r.coords) ? r.coords[1] : undefined);
            if (typeof lat === 'string') lat = parseFloat(lat);
            if (typeof lng === 'string') lng = parseFloat(lng);

            // 대한민국 범위 기준으로 뒤집힘 보정
            if (lat != null && lng != null) {
                if ((lat > 132 || lat < 110) && lng >= 33 && lng <= 39) {
                    const tmp = lat;
                    lat = lng;
                    lng = tmp;
                }
            }
            if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) return;

            const count = Number(firstDefined(r.count, r.cnt, r.n, 0) || 0);
            const t = count / cMax;
            const radius = 6 + Math.sqrt(Math.max(count, 1)) * 2;
            const color = blueColor(t);
            const region = firstDefined(r.region, r.addr, '지역');
            const tip = '<div><strong>' + region + '</strong><br/>건수: ' + count + '</div>';
            const pair = makeCircleWithHalo(lat, lng, radius, color, tip);
            pair[0].addTo(LAYER_POINTS);
            pair[1].addTo(LAYER_POINTS);
            bounds.push([lat, lng]);
        });

        LAYER_POINTS.addTo(LMAP);
        if (bounds.length && !MAP_LOCKED) {
            const b = L.latLngBounds(bounds);
            LMAP.fitBounds(b.pad(0.15), { maxZoom: 12 });
        }
    } catch (e) {
        console.error('[analytics] renderLeafletPoints error', e);
    }
}

/* ===== 이벤트/초기화 ===== */
document.addEventListener('DOMContentLoaded', function() {
    fillYears('year-global');

    const sel = $('year-global'),
        btn = $('apply-global');
    const go = function() {
        const y = Number(sel.value) || new Date().getFullYear();
        setParam('year', y);
        loadAll(y);
    };
    btn.addEventListener('click', go);
    sel.addEventListener('change', go);

    window.addEventListener('resize', function() {
        loadAll(CURRENT_YEAR);
        if (LMAP) LMAP.invalidateSize();
    });

    const mapApply = document.getElementById('map-apply');
    if (mapApply) mapApply.addEventListener('click', renderLeafletPoints);

    const mapLock = document.getElementById('map-lock');
    if (mapLock) {
        mapLock.addEventListener('click', function() {
            MAP_LOCKED = !MAP_LOCKED;
            applyMapLockState();
        });
    }

    go(); // 최초 로드
});
