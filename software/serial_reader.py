"""Bộ đọc UART chạy luồng riêng + chế độ replay (VIE-09).

Kiến trúc producer–consumer:
  ReaderThread (producer)  : đọc byte từ cổng COM (hoặc file replay), cắt theo '\\n', ghi NGUYÊN VĂN từng
                             dòng xuống file raw NGAY khi nhận (flush mỗi dòng), parse, đẩy Packet vào queue.
  GUI / Analysis (consumer): lấy gói khỏi queue theo chu kỳ (after(33 ms) ≈ 30 fps).

- Không bao giờ đọc serial trong luồng giao diện.
- queue.Queue tự khóa (thread-safe), có giới hạn để không ăn hết RAM nếu GUI treo. Nếu queue đầy,
  gói bị bỏ khỏi HIỂN THỊ (đếm ở n_overflow) nhưng VẪN nằm trong file raw — dữ liệu không mất.
- Rút cáp / lỗi cổng: SerialException được bắt trong luồng đọc, file raw được đóng an toàn, phần dòng
  dở dang cũng được ghi lại, rồi báo về GUI qua `error`, sự kiện `finished` và callback `on_error`.
- Đầu file raw có metadata phiên đo: phiên bản phần cứng/firmware/đường khí + nội dung
  config/hardware_measured_params.json (thông số Nhung đo thực tế) nếu có.

Băng thông: 230400 bps 8N1 ≈ 23 040 byte/s; dòng dài nhất 32 byte × 500 dòng/s = 16 000 byte/s (~70 %).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from . import PROJECT_ROOT
from .parser import StreamParser

try:
    import serial
    import serial.tools.list_ports
except ImportError:          # cho phép chạy replay khi chưa cài pyserial
    serial = None

HW_PARAMS_PATH = PROJECT_ROOT / "config" / "hardware_measured_params.json"
DEFAULT_BAUD = 230400


def list_ports():
    """Danh sách cổng COM đang có (rỗng nếu chưa cài pyserial)."""
    if serial is None:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


def session_metadata(cfg: dict | None = None, hw_params_path: str | Path | None = None, **extra) -> dict:
    """Metadata ghi ở đầu file raw: thời điểm, phiên bản, thông số đo thực tế của phần cứng."""
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "protocol": "protocol_v1"}
    if cfg:
        for k in ("hardware_version", "firmware_version", "airpath_version", "sample_rate_hz", "calibration_id"):
            if k in cfg:
                meta[k] = cfg[k]
    p = Path(hw_params_path) if hw_params_path else HW_PARAMS_PATH
    if p.exists():
        try:
            meta["hardware_measured_params"] = json.dumps(json.loads(p.read_text(encoding="utf-8")),
                                                          ensure_ascii=False, separators=(",", ":"))
        except (OSError, ValueError) as e:
            meta["hardware_measured_params_error"] = f"{type(e).__name__}: {e}"
    meta.update(extra)
    return meta


class ReaderThread(threading.Thread):
    """Luồng đọc nền. Dùng: r = ReaderThread(q, port="COM5", raw_log=...); r.start(); ...; r.stop()."""

    def __init__(self, out_queue: queue.Queue, port: str | None = None, baud: int = DEFAULT_BAUD,
                 replay_file: str | Path | None = None, replay_speed: float = 1.0,
                 raw_log: str | Path | None = None, metadata: dict | None = None,
                 on_error=None):
        super().__init__(daemon=True)
        if not port and not replay_file:
            raise ValueError("Cần port hoặc replay_file")
        self.q = out_queue
        self.port, self.baud = port, baud
        self.replay_file = Path(replay_file) if replay_file else None
        self.replay_speed = replay_speed
        self.raw_log = Path(raw_log) if raw_log else None
        self.metadata = metadata or {}
        self.on_error = on_error
        self.parser = StreamParser()
        self._stop = threading.Event()
        self.finished = threading.Event()
        self.error: str | None = None
        self.n_overflow = 0
        self.n_bytes = 0
        self._last_nl = True

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------------------
    def _emit(self, raw: bytes, fh):
        """Một dòng thô (bytes, có thể kèm '\\r\\n'): ghi nguyên văn + flush, rồi parse và đẩy vào queue."""
        if fh:
            fh.write(raw)
            fh.flush()                                   # chống mất dữ liệu nếu ứng dụng bị tắt đột ngột
        self.n_bytes += len(raw)
        self._last_nl = raw.endswith(b"\n")
        line = raw.decode("ascii", errors="replace")
        if line.startswith("#") or not line.strip():
            return
        p = self.parser.feed(line)
        if p is not None:
            try:
                self.q.put_nowait(p)
            except queue.Full:
                self.n_overflow += 1

    def _open_log(self):
        if not self.raw_log:
            return None
        self.raw_log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.raw_log, "wb")
        for k, v in self.metadata.items():
            fh.write(f"# {k}={v}\n".encode("utf-8"))
        fh.flush()
        return fh

    def run(self):
        fh = None
        try:
            fh = self._open_log()
            if self.replay_file:
                self._run_replay(fh)
            else:
                self._run_serial(fh)
        except Exception as e:                         # báo lỗi cho GUI, không làm sập chương trình
            self.error = f"{type(e).__name__}: {e}"
        finally:
            if fh:
                reason = self.error or "stopped"
                if not self._last_nl:
                    fh.write(b"\n")                    # tách dòng dở dang (lúc rút cáp) khỏi dòng kết thúc
                fh.write(f"# end={datetime.now().isoformat(timespec='seconds')} reason={reason}\n".encode("utf-8"))
                fh.close()
            self.finished.set()
            if self.error and self.on_error:
                try:
                    self.on_error(self.error)
                except Exception:
                    pass

    def _run_serial(self, fh):
        if serial is None:
            raise RuntimeError("Chưa cài pyserial: pip install pyserial")
        buf = b""
        try:
            with serial.Serial(self.port, self.baud, timeout=0.1) as ser:
                ser.reset_input_buffer()
                while not self._stop.is_set():
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue
                    buf += chunk
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        self._emit(raw + b"\n", fh)
        finally:
            if buf:                                    # phần dòng dở dang lúc rút cáp: vẫn ghi lại
                self._emit(buf, fh)

    def _run_replay(self, fh):
        """Phát lại file raw theo nhịp t_us thật (replay_speed=1), nhanh gấp k lần (k), hoặc tối đa (0)."""
        t_wall0, t_dev0 = time.perf_counter(), None
        with open(self.replay_file, "rb") as f:
            for raw in f:
                if self._stop.is_set():
                    break
                if raw.startswith(b"#"):
                    continue
                self._emit(raw, fh)
                last = self.parser._prev
                if last is None or self.replay_speed <= 0:
                    continue
                if t_dev0 is None:
                    t_dev0 = last.t_us
                due = (last.t_us - t_dev0) * 1e-6 / self.replay_speed
                lag = due - (time.perf_counter() - t_wall0)
                if lag > 0.005:
                    time.sleep(lag)
