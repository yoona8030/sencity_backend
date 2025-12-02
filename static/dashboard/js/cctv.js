// static/dashboard/js/cctv.js
(function () {
  'use strict';

  /* =============== 공통 유틸 =============== */
  function $(s, el) {
    return (el || document).querySelector(s);
  }

  function $all(s, el) {
    return Array.prototype.slice.call((el || document).querySelectorAll(s));
  }

  function readCsrfToken() {
    function getCookie(name) {
      var value = '; ' + document.cookie;
      var parts = value.split('; ' + name + '=');
      if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
      return null;
    }
    return getCookie('csrftoken') || (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  }

  function parseJSONSafe(text, fallback) {
    try {
      return JSON.parse(text);
    } catch (_e) {
      return typeof fallback === 'undefined' ? null : fallback;
    }
  }

  function safeFetch(url, opt) {
    opt = opt || {};
    opt.credentials = 'same-origin';
    opt.method = (opt.method || 'GET').toUpperCase();

    if (opt.body && typeof opt.body === 'object' && !(opt.body instanceof FormData)) {
      opt.headers = opt.headers || {};
      opt.headers['Content-Type'] = opt.headers['Content-Type'] || 'application/json';
      opt.body = JSON.stringify(opt.body);
    }

    if (opt.method !== 'GET' && opt.method !== 'HEAD') {
      opt.headers = opt.headers || {};
      opt.headers['X-CSRFToken'] = readCsrfToken();
    }

    return fetch(url, opt).then(function (res) {
      return res.text().then(function (txt) {
        var data = parseJSONSafe(txt, {});
        if (!res.ok) {
          var msg = (data && (data.detail || data.error)) || 'HTTP ' + res.status;
          var err = new Error(msg);
          err.response = res;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  /* =============== 상수 / 상태 =============== */
  var API_DEVICES = '/dashboard/api/cctv-devices/';
  var API_SENSORS = '/dashboard/api/cctv-sensors/';

  // YOLO API: min_conf 는 백엔드 threshold (0.2 정도)
  var YOLO_API = '/api/ai/classify-yolo/?min_conf=0.2';

  // ★ 백엔드 YOLO on/off 토글 (지금은 끔)
  var YOLO_ENABLED = false;

  // 카메라별 "화면 표시용" 소스
  // 1번: ESP32 스트림 (진짜 움직이는 CCTV)
  // 2~4번: 데모용
  var CAM_SOURCES = {
    1: { type: 'video', src: '/static/dashboard/videos/yolovd.mp4' }, // Flask YOLO
    2: { type: 'video', src: '/static/dashboard/videos/sample.mp4' },
    3: { type: 'video', src: '/static/dashboard/videos/sample1.mp4' },
    4: { type: 'image', src: '/static/dashboard/images/logo.png' },
  };

  var img, video, vsrc;
  var webcamStream = null;
  var currentCamNo = 1;
  var currentSourceMode = 'webcam'; // 'webcam' | 'cctv'

  // YOLO 결과 히스토리(최근 N 프레임)
  var YOLO_HISTORY = [];
  var MAX_HISTORY = 10;
  var DISPLAY_THRESHOLD = 0.3; // 평균 score 0.3 미만이면 화면에는 안 그림

  /* =============== 좌측 목록 =============== */
  function renderDevices(items) {
    var list = $('#device-list');
    if (!list) return;
    if (!items || !items.length) {
      list.innerHTML =
        '<li class="device-item offline"><div class="device-left"><div class="device-info">' +
        '<div class="name">등록된 카메라가 없습니다.</div><div class="state">EMPTY</div>' +
        '</div></div></li>';
      return;
    }
    var html = '';
    for (var i = 0; i < items.length; i++) {
      var d = items[i],
        idx = i + 1,
        online = !!d.online;
      html +=
        '<li class="device-item ' +
        (online ? 'online' : 'offline') +
        ' clickable" data-cam="' +
        idx +
        '">' +
        '  <div class="device-left"><div class="device-info">' +
        '    <div class="name">' +
        (d.name || 'CCTV ' + idx) +
        '</div>' +
        '    <div class="state">' +
        (online ? 'ONLINE' : 'OFFLINE') +
        '</div>' +
        '  </div></div><span class="dot ' +
        (online ? 'ok' : 'bad') +
        '"></span></li>';
    }
    list.innerHTML = html;
  }

  function renderSensors(items) {
    var grid = $('#sensor-grid');
    if (!grid) return;
    if (!items || !items.length) {
      grid.innerHTML = '<div class="sensor">센서 데이터가 없습니다.</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < items.length; i++) {
      var s = items[i],
        idx = i + 1,
        det = !!s.detected;
      html +=
        '<div class="sensor ' +
        (det ? 'detected' : '') +
        ' clickable" data-cam="' +
        idx +
        '">' +
        '  <div class="sensor-name">' +
        (s.name || 'CCTV ' + idx) +
        '</div>' +
        '  <div class="sensor-text">' +
        (det ? '구역 감지됨' : '구역 오프라인') +
        '</div>' +
        '</div>';
    }
    grid.innerHTML = html;
  }

  function updateLeftStatus(selectedCamNo) {
    var devs = $all('#device-list .device-item');
    for (var i = 0; i < devs.length; i++) {
      var el = devs[i];
      var cam = Number(el.getAttribute('data-cam'));
      var on = cam === Number(selectedCamNo);
      el.classList.toggle('active', on);
      el.classList.toggle('online', on);
      el.classList.toggle('offline', !on);
      var st = el.querySelector('.device-info .state');
      if (st) st.textContent = on ? 'ONLINE' : 'OFFLINE';
      var dot = el.querySelector('.dot');
      if (dot) {
        dot.classList.toggle('ok', on);
        dot.classList.toggle('bad', !on);
      }
    }
    var sens = $all('#sensor-grid .sensor');
    for (var j = 0; j < sens.length; j++) {
      var se = sens[j];
      var cam2 = Number(se.getAttribute('data-cam'));
      var on2 = cam2 === Number(selectedCamNo);
      se.classList.toggle('active', on2);
      se.classList.toggle('detected', on2);
      var txt = se.querySelector('.sensor-text');
      if (txt) txt.textContent = on2 ? '구역 감지됨' : '구역 오프라인';
    }
  }

  /* =============== 뷰어: 외부 CCTV/데모 =============== */

  // 일반 "정지 이미지" 소스 (로컬 이미지, 데모용)
  function showImage(src, label) {
    try {
      if (video) {
        video.pause();
        if (webcamStream) {
          webcamStream.getTracks().forEach(function (t) {
            t.stop();
          });
          webcamStream = null;
        }
        video.srcObject = null;
      }
    } catch (_e) {}
    if (video) video.style.display = 'none';
    if (!img) return;

    var url = src;
    // 일반 이미지에는 캐시 방지 쿼리 붙이기
    var bust = '_ts=' + Date.now();
    url = url.indexOf('?') >= 0 ? url + '&' + bust : url + '?' + bust;

    img.onerror = function () {
      console.warn('이미지를 불러오지 못했습니다:', url);
    };
    img.src = url;
    img.alt = label || '';
    img.style.display = 'block';
  }

  // ESP32 스트림용 (MJPEG) → src 한 번만 설정하면 계속 움직임
  function showStream(src, label) {
    try {
      if (video) {
        video.pause();
        if (webcamStream) {
          webcamStream.getTracks().forEach(function (t) {
            t.stop();
          });
          webcamStream = null;
        }
        video.srcObject = null;
      }
    } catch (_e) {}
    if (video) video.style.display = 'none';
    if (!img) return;

    img.onerror = function () {
      console.warn('스트림을 불러오지 못했습니다:', src);
    };
    img.src = src; // 캐시 버스터 X, 스트림 그대로
    img.alt = label || '';
    img.style.display = 'block';
  }

  function showVideoFile(src, label) {
    if (!video || !vsrc) return;
    if (img) img.style.display = 'none';

    if (webcamStream) {
      webcamStream.getTracks().forEach(function (t) {
        t.stop();
      });
      webcamStream = null;
    }

    video.srcObject = null;
    if (vsrc.src !== src) vsrc.src = src;
    video.load();
    video.style.display = 'block';
    video.play().catch(function () {});
  }

  /* =============== 노트북 웹캠 =============== */
  function startWebcam() {
    if (!video) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('이 브라우저에서는 웹캠을 사용할 수 없습니다.');
      return;
    }

    if (img) img.style.display = 'none';
    video.style.display = 'block';

    navigator.mediaDevices
      .getUserMedia({ video: true, audio: false })
      .then(function (stream) {
        webcamStream = stream;
        video.srcObject = stream;
        video.play().catch(function () {});
      })
      .catch(function (err) {
        console.error('웹캠 오류:', err);
        alert('웹캠에 접근할 수 없습니다. 권한을 허용했는지 확인하세요.');
      });
  }

  function stopWebcam() {
    if (webcamStream) {
      webcamStream.getTracks().forEach(function (t) {
        t.stop();
      });
      webcamStream = null;
    }
    if (video) {
      video.pause();
      video.srcObject = null;
    }
  }

  /* =============== YOLO 결과 히스토리/스무딩 =============== */

  function resetYoloHistory() {
    YOLO_HISTORY.length = 0;
  }

  function pushYoloResult(data) {
    if (!data || !data.label || !data.bbox) return;
    YOLO_HISTORY.push(data);
    if (YOLO_HISTORY.length > MAX_HISTORY) {
      YOLO_HISTORY.shift();
    }
  }

  function getSmoothedResult() {
    if (!YOLO_HISTORY.length) return null;

    var counts = {};
    var sumScores = {};
    var lastBox = {};

    for (var i = 0; i < YOLO_HISTORY.length; i++) {
      var r = YOLO_HISTORY[i];
      var lb = r.label;
      if (!lb) continue;
      counts[lb] = (counts[lb] || 0) + 1;
      sumScores[lb] = (sumScores[lb] || 0) + (r.score || 0);
      lastBox[lb] = r.bbox;
    }

    var bestLabel = null;
    var bestCount = 0;

    for (var label in counts) {
      if (!Object.prototype.hasOwnProperty.call(counts, label)) continue;
      var c = counts[label];
      if (c > bestCount) {
        bestCount = c;
        bestLabel = label;
      }
    }

    if (!bestLabel) return null;

    var avgScore = (sumScores[bestLabel] || 0) / counts[bestLabel];

    if (avgScore < DISPLAY_THRESHOLD) {
      return null;
    }

    return {
      label: bestLabel,
      score: avgScore.toFixed(3),
      bbox: lastBox[bestLabel],
    };
  }

  function captureWebcamFrame() {
    return new Promise(function (resolve) {
      if (!video || !video.videoWidth || !video.videoHeight) return resolve(null);
      var canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        function (blob) {
          resolve(blob);
        },
        'image/jpeg',
        0.9
      );
    });
  }

  function drawYoloBox(result) {
    var overlay = $('#yolo-overlay');
    if (!overlay) return;
    overlay.innerHTML = '';

    if (!result || !result.bbox || result.label == null) {
      return;
    }

    var targetEl = currentSourceMode === 'webcam' ? video : img;
    if (!targetEl || targetEl.style.display === 'none') return;
    var natW = targetEl.videoWidth || targetEl.naturalWidth;
    var natH = targetEl.videoHeight || targetEl.naturalHeight;
    if (!natW || !natH) return;

    var rect = targetEl.getBoundingClientRect();
    var scaleX = rect.width / natW;
    var scaleY = rect.height / natH;

    var x = result.bbox.x1 * scaleX;
    var y = result.bbox.y1 * scaleY;
    var w = (result.bbox.x2 - result.bbox.x1) * scaleX;
    var h = (result.bbox.y2 - result.bbox.y1) * scaleY;

    var box = document.createElement('div');
    box.className = 'yolo-box';
    box.style.left = x + 'px';
    box.style.top = y + 'px';
    box.style.width = w + 'px';
    box.style.height = h + 'px';
    box.textContent = result.label + ' (' + result.score + ')';

    overlay.appendChild(box);
  }

  function yoloDetect() {
    // YOLO 전체 비활성화 옵션
    if (!YOLO_ENABLED) {
      return;
    }

    // 비디오/이미지가 준비 안 됐으면 패스
    if (currentSourceMode === 'webcam') {
      if (!video || !webcamStream) return;
    } else {
      if (!img || !img.src) return;
    }

    var blobPromise;
    if (currentSourceMode === 'webcam') {
      blobPromise = captureWebcamFrame();
    } else {
      // 1번 CCTV만 프록시 사용
      if (currentCamNo !== 1) {
        return; // 2~4번은 YOLO 실행 안 함
      }
      var proxyUrl = '/dashboard/api/cctv-proxy-frame/?cam=1&_yts=' + Date.now();

      blobPromise = fetch(proxyUrl, { cache: 'no-store' }).then(function (r) {
        if (!r.ok) return null;
        return r.blob();
      });
    }

    blobPromise
      .then(function (blob) {
        if (!blob) return;
        var fd = new FormData();
        fd.append('image', blob, 'frame.jpg');
        return safeFetch(YOLO_API, {
          method: 'POST',
          body: fd,
        });
      })
      .then(function (data) {
        if (!data) return;
        pushYoloResult(data);
        var smoothed = getSmoothedResult();
        drawYoloBox(smoothed);
      })
      .catch(function (err) {
        console.warn('YOLO detect error:', err);
      });
  }

  /* =============== 카메라 / 소스 전환 =============== */

  function applySourceMode() {
    var title = $('#viewer-title'),
      foot = $('#viewer-foot');
    if (title) title.textContent = '실시간 영상';
    if (foot) foot.textContent = '카메라 ' + currentCamNo;

    resetYoloHistory();

    if (currentSourceMode === 'webcam') {
      stopWebcam();
      startWebcam();
    } else {
      stopWebcam();
      var cfg = CAM_SOURCES[currentCamNo] || CAM_SOURCES[1];
      if (cfg.type === 'video') {
        showVideoFile(cfg.src, '카메라 ' + currentCamNo);
      } else if (cfg.type === 'stream') {
        showStream(cfg.src, '카메라 ' + currentCamNo);
      } else {
        showImage(cfg.src, '카메라 ' + currentCamNo);
      }
    }

    updateLeftStatus(currentCamNo);
  }

  function bindCamTabs() {
    var tabs = $all('.cam-tab');

    function activate(n) {
      currentCamNo = Number(n);
      for (var i = 0; i < tabs.length; i++) {
        var b = tabs[i];
        var on = b.getAttribute('data-cam') === String(n);
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      }
      applySourceMode();
    }

    for (var i = 0; i < tabs.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          activate(btn.getAttribute('data-cam'));
        });
      })(tabs[i]);
    }

    var devList = $('#device-list');
    if (devList)
      devList.addEventListener('click', function (e) {
        var item = e.target && e.target.closest ? e.target.closest('.device-item[data-cam]') : null;
        if (!item) return;
        activate(item.getAttribute('data-cam'));
      });

    var senGrid = $('#sensor-grid');
    if (senGrid)
      senGrid.addEventListener('click', function (e) {
        var card = e.target && e.target.closest ? e.target.closest('.sensor[data-cam]') : null;
        if (!card) return;
        activate(card.getAttribute('data-cam'));
      });

    // 기본 카메라 1번
    activate(1);
  }

  function bindSourceToggle() {
    var btns = $all('.src-btn');
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-src');
        if (mode === currentSourceMode) return;
        currentSourceMode = mode;

        btns.forEach(function (b) {
          b.classList.toggle('is-active', b === btn);
        });

        applySourceMode();
      });
    });
  }

  /* =============== 초기화 =============== */
  document.addEventListener('DOMContentLoaded', function () {
    img = $('#viewer-img');
    video = $('#viewer-video');
    vsrc = $('#viewer-source');

    safeFetch(API_DEVICES)
      .then(renderDevices)
      .catch(function () {
        renderDevices([
          { name: 'CCTV 1', online: true },
          { name: 'CCTV 2', online: false },
          { name: 'CCTV 3', online: true },
          { name: 'CCTV 4', online: false },
        ]);
      });

    safeFetch(API_SENSORS)
      .then(renderSensors)
      .catch(function () {
        renderSensors([
          { name: 'CCTV 1', detected: true },
          { name: 'CCTV 2', detected: false },
          { name: 'CCTV 3', detected: false },
          { name: 'CCTV 4', detected: false },
        ]);
      });

    bindCamTabs();
    bindSourceToggle();

    // ★ 백엔드 YOLO가 켜져 있을 때만 주기 실행
    if (YOLO_ENABLED) {
      setInterval(yoloDetect, 1500);
    }
  });
})();
