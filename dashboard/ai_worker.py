# dashboard/ai_worker.py
# -*- coding: utf-8 -*-
import threading
import time
import requests
import re
import cv2
import numpy as np

class MjpegClient:
    """MJPEG 멀티파트를 직접 파싱해 프레임(np.ndarray BGR)을 yield합니다."""
    def __init__(self, url: str, timeout_open: float = 10.0, timeout_read: float = 15.0):
        self.url = url
        self.timeout_open = timeout_open
        self.timeout_read = timeout_read
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "multipart/x-mixed-replace, image/jpeg, */*",
            "Connection": "keep-alive",
        })
        adapter = requests.adapters.HTTPAdapter(max_retries=2, pool_connections=1, pool_maxsize=1)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.boundary = None
        self._resp = None

    def _read_headers_and_boundary(self):
        ct = self._resp.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ct, re.I)
        if m:
            self.boundary = m.group(1).strip().strip('"')
            if not self.boundary.startswith("--"):
                self.boundary = "--" + self.boundary

    def frames(self):
        self._resp = self.session.get(self.url, stream=True, timeout=self.timeout_open)
        self._resp.raise_for_status()
        self._read_headers_and_boundary()

        boundary = (self.boundary or "").encode("ascii", "ignore")
        buf = bytearray()
        for chunk in self._resp.iter_content(chunk_size=4096):
            if not chunk: continue
            buf.extend(chunk)

            if not boundary and b"--" in buf:
                m = re.search(br"\r?\n(--[^\r\n]+)\r?\n", buf)
                if m: boundary = m.group(1)

            if not boundary:
                if len(buf) > 131072:  # 128KB 넘어도 바운더리 없음 → 포기
                    raise RuntimeError("MJPEG boundary not found")
                continue

            while True:
                try:
                    idx = buf.index(boundary)
                except ValueError:
                    break
                if idx > 0: del buf[:idx]
                del buf[:len(boundary)]
                if len(buf) >= 2 and buf[0:2] == b"\r\n": del buf[:2]

                try:
                    header_end = buf.index(b"\r\n\r\n")
                except ValueError:
                    break

                headers_raw = bytes(buf[:header_end]).decode("iso-8859-1", "ignore")
                del buf[:header_end + 4]

                m_len = re.search(r"Content-Length:\s*(\d+)", headers_raw, re.I)
                if m_len:
                    need = int(m_len.group(1))
                    if len(buf) < need: break
                    body = bytes(buf[:need]); del buf[:need]
                else:
                    try:
                        soi = buf.index(b"\xff\xd8")
                        eoi = buf.index(b"\xff\xd9", soi+2)
                    except ValueError:
                        break
                    body = bytes(buf[soi:eoi+2]); del buf[:eoi+2]

                img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    yield img

class StreamWorker(threading.Thread):
    """/stream 시 MJPEG 파서, /capture 시 스냅샷 폴링으로 프레임 획득."""
    def __init__(self, src: str, snapshot_fallback: bool = True, snapshot_interval_ms: int = 350):
        super().__init__(daemon=True)
        self.src = src
        self.snapshot_fallback = snapshot_fallback
        self.snapshot_interval_ms = snapshot_interval_ms  # 350ms ≈ 2.8fps
        self._stop = threading.Event()
        self.last_frame = None
        self.ok = False
        self.err = None

    def stop(self): self._stop.set()

    def _snapshot_once(self):
        try:
            r = requests.get(self.src, timeout=5)
            r.raise_for_status()
            return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:
            self.err = f"snapshot error: {e}"
            return None

    def run(self):
        # 1) /stream 인지 검사
        if "/stream" in self.src:
            try:
                client = MjpegClient(self.src, timeout_open=10.0, timeout_read=15.0)
                for frame in client.frames():
                    if self._stop.is_set(): break
                    self.last_frame = frame
                    self.ok = True
            except Exception as e:
                self.ok = False
                self.err = f"mjpeg error: {e}"

        # 2) /capture (또는 /stream 실패 시 폴백)
        if ("/capture" in self.src) or (not self.ok and self.snapshot_fallback):
            while not self._stop.is_set():
                img = self._snapshot_once()
                if img is not None:
                    self.last_frame = img; self.ok = True
                time.sleep(self.snapshot_interval_ms / 1000.0)

class YoloInfer(threading.Thread):
    def __init__(self, stream: StreamWorker, model, conf_thres: float = 0.15):
        super().__init__(daemon=True)
        self.stream = stream
        self.model = model
        self.conf_thres = float(conf_thres)
        self._stop = threading.Event()
        self.detections = []
        self.total_animals = 0
        self.last_jpeg_base64 = None

    def stop(self): self._stop.set()

    def run(self):
        import base64
        while not self._stop.is_set():
            frame = self.stream.last_frame
            if frame is None:
                time.sleep(0.02); continue
            try:
                results = self.model(frame, size=640)
                dets, total = [], 0
                for *xyxy, conf, cls in results.xyxy[0].tolist():
                    c = float(conf)
                    if c < self.conf_thres: continue
                    x1, y1, x2, y2 = [int(v) for v in xyxy]
                    name = self.model.names[int(cls)]
                    total += 1
                    dets.append({"animal_name": name, "confidence": c, "bbox": [x1,y1,x2,y2]})
                self.detections = dets; self.total_animals = total

                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    self.last_jpeg_base64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
            except Exception:
                pass
            time.sleep(0.02)
