"""Unit test VIE-09: luồng đọc UART nền, replay, ghi raw tức thời, rút cáp đột ngột."""
import json
import queue
import time

import pytest

from software import serial_reader as SR
from software.parser import format_line


def lines(n, seq0=0, t0=1_000_000):
    return [format_line(seq0 + i, t0 + 2000 * i, 2068 + i % 7).encode("ascii") for i in range(n)]


def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def wait(r, timeout=10):
    assert r.finished.wait(timeout), "luồng đọc không kết thúc"


# ---- replay ----------------------------------------------------------------------------------
def test_replay_delivers_every_packet_and_raw_is_verbatim(tmp_path):
    src = tmp_path / "src.csv"
    data = lines(5000)
    src.write_bytes(b"# nguon\n" + b"".join(data))
    q = queue.Queue()
    r = SR.ReaderThread(q, replay_file=src, replay_speed=0, raw_log=tmp_path / "raw.csv",
                        metadata={"hardware_version": "hw_v1.0"})
    r.start()
    wait(r)
    got = drain(q)
    assert r.error is None and r.n_overflow == 0
    assert [p.seq for p in got] == list(range(5000))                 # không rơi mẫu, đúng thứ tự
    raw = (tmp_path / "raw.csv").read_bytes().splitlines(keepends=True)
    body = [ln for ln in raw if not ln.startswith(b"#")]
    assert body == data                                               # ghi nguyên văn từng byte
    assert raw[0] == b"# hardware_version=hw_v1.0\n"
    assert raw[-1].startswith(b"# end=") and b"reason=stopped" in raw[-1]


def test_replay_realtime_pacing(tmp_path):
    src = tmp_path / "src.csv"
    src.write_bytes(b"".join(lines(500)))                             # 500 mẫu = 1.0 s ở 500 Hz
    q = queue.Queue()
    r = SR.ReaderThread(q, replay_file=src, replay_speed=1.0)
    t0 = time.perf_counter()
    r.start()
    wait(r)
    dt = time.perf_counter() - t0
    assert 0.9 <= dt <= 1.5, dt
    assert len(drain(q)) == 500


def test_replay_keeps_bad_lines_in_raw_and_counts_them(tmp_path):
    src = tmp_path / "src.csv"
    good = lines(10)
    src.write_bytes(b"".join(good[:5]) + b"$DAT,5,11000,20\r\n" + b"".join(good[6:]))
    q = queue.Queue()
    r = SR.ReaderThread(q, replay_file=src, replay_speed=0, raw_log=tmp_path / "raw.csv")
    r.start()
    wait(r)
    assert len(drain(q)) == 9
    assert r.parser.summary()["TRUNCATED_LINE"] == 1
    assert b"$DAT,5,11000,20\r\n" in (tmp_path / "raw.csv").read_bytes()


def test_queue_full_drops_display_only_not_raw(tmp_path):
    src = tmp_path / "src.csv"
    src.write_bytes(b"".join(lines(300)))
    q = queue.Queue(maxsize=50)                                       # GUI "treo", không lấy gói
    r = SR.ReaderThread(q, replay_file=src, replay_speed=0, raw_log=tmp_path / "raw.csv")
    r.start()
    wait(r)
    assert q.qsize() == 50 and r.n_overflow == 250
    body = [ln for ln in (tmp_path / "raw.csv").read_bytes().splitlines() if not ln.startswith(b"#")]
    assert len(body) == 300                                           # file raw vẫn đủ


# ---- cổng COM giả: tốc độ 230400 và rút cáp ----------------------------------------------------
class FakeSerialException(OSError):
    pass


def make_fake_serial(payload: bytes, fail_after: int | None, chunk=64):
    """Cổng COM giả: trả payload theo từng mảnh; sau fail_after byte thì ném SerialException (rút cáp)."""
    class FakeSerial:
        opened_with = {}
        delivered = b""

        def __init__(self, port, baud, timeout=None):
            FakeSerial.opened_with = {"port": port, "baud": baud}
            self.pos = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def reset_input_buffer(self):
            pass

        @property
        def in_waiting(self):
            return min(chunk, len(payload) - self.pos)

        def read(self, n):
            if fail_after is not None and self.pos >= fail_after:
                raise FakeSerialException("ClearCommError failed (thiết bị bị rút)")
            if self.pos >= len(payload):
                time.sleep(0.01)
                return b""
            end = self.pos + max(n, 1)
            if fail_after is not None:
                end = min(end, fail_after)
            b = payload[self.pos:end]
            self.pos += len(b)
            FakeSerial.delivered = payload[:self.pos]
            return b

    class FakeModule:
        Serial = FakeSerial
        SerialException = FakeSerialException
    return FakeModule, FakeSerial


def test_serial_reads_all_at_230400(tmp_path, monkeypatch):
    data = lines(2000)
    mod, cls = make_fake_serial(b"".join(data), fail_after=None)
    monkeypatch.setattr(SR, "serial", mod)
    q = queue.Queue()
    r = SR.ReaderThread(q, port="COM5", raw_log=tmp_path / "raw.csv")
    r.start()
    deadline = time.time() + 5
    got = []
    while len(got) < 2000 and time.time() < deadline:
        got += drain(q)
        time.sleep(0.01)
    r.stop()
    wait(r)
    assert cls.opened_with == {"port": "COM5", "baud": 230400}
    assert [p.seq for p in got] == list(range(2000))


def test_unplug_cable_is_caught_and_signalled(tmp_path, monkeypatch):
    data = b"".join(lines(1000))
    cut = len(data) // 2 + 7                                          # rút cáp giữa chừng một dòng
    mod, cls = make_fake_serial(data, fail_after=cut)
    monkeypatch.setattr(SR, "serial", mod)
    q = queue.Queue()
    errors = []
    r = SR.ReaderThread(q, port="COM5", raw_log=tmp_path / "raw.csv", on_error=errors.append)
    r.start()
    wait(r)
    assert r.error and "FakeSerialException" in r.error              # không sập, báo lỗi về GUI
    assert errors == [r.error]
    raw = (tmp_path / "raw.csv").read_bytes()
    body = b"".join(ln for ln in raw.splitlines(keepends=True) if not ln.startswith(b"#"))
    assert cls.delivered == data[:cut]
    assert body == cls.delivered + b"\n"                             # mọi byte nhận được đều đã ghi (+ xuống dòng tách)
    assert b"reason=FakeSerialException" in raw
    assert len(drain(q)) == r.parser.n_valid


def test_missing_pyserial_reports_error(monkeypatch):
    monkeypatch.setattr(SR, "serial", None)
    r = SR.ReaderThread(queue.Queue(), port="COM5")
    r.start()
    wait(r)
    assert "pyserial" in r.error


# ---- metadata ------------------------------------------------------------------------------
def test_session_metadata_includes_hardware_params(tmp_path, cfg):
    hw = tmp_path / "hardware_measured_params.json"
    hw.write_text(json.dumps({"vs_measured_v": 4.97, "vref_v": 3.29}), encoding="utf-8")
    meta = SR.session_metadata(cfg, hw_params_path=hw, source="COM5")
    assert meta["hardware_version"] == cfg["hardware_version"]
    assert json.loads(meta["hardware_measured_params"]) == {"vs_measured_v": 4.97, "vref_v": 3.29}
    assert meta["source"] == "COM5" and meta["protocol"] == "protocol_v1"


def test_session_metadata_without_hw_file(tmp_path, cfg):
    meta = SR.session_metadata(cfg, hw_params_path=tmp_path / "khong_co.json")
    assert "hardware_measured_params" not in meta


def test_requires_port_or_replay():
    with pytest.raises(ValueError):
        SR.ReaderThread(queue.Queue())
