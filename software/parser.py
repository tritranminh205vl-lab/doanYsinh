"""Parser giao thức protocol_v1 của Quang + chính sách mất mẫu (VIE-04, Chương 3).

Lớp vật lý: UART 230400 baud, 8N1, mỗi mẫu ADC (500 Hz) là một dòng ASCII.

Khung:  $DAT,<seq>,<t_us>,<adc_raw>,<chk>*\\r\\n
  - chk  : XOR từng byte ASCII của chuỗi nằm giữa '$' và dấu phẩy trước <chk>
           ("DAT,<seq>,<t_us>,<adc_raw>"), ghi 2 chữ số hex (nhận cả hoa lẫn thường).
  - seq  : uint16, quay vòng 65536  ->  Δseq = (seq[n] − seq[n−1]) mod 65536
  - t_us : uint32 micro-giây của MCU, tràn sau 2^32 µs ≈ 71.58 phút

Năm quy tắc kiểm tra (sổ tay mục 3.1):
  1. Tiền tố "$DAT," + hậu tố "*"           -> sai: TRUNCATED_LINE (dòng bị loại)
  2. XOR checksum                           -> sai: CORRUPTED_PACKET (dòng bị loại)
  3. Δseq > 1                               -> SEQ_DROP, mất (Δseq − 1) mẫu
  4. t_us giảm nhưng là tràn thật           -> TS_WRAP, cộng 2^32 (trục thời gian không ngắt)
  5. t_us giảm và seq < 10                  -> NEW_SESSION_MCU_RESET (mở phiên mới)
Bổ sung để không bao giờ hiểu sai trục thời gian / không mất mẫu oan:
  - byte rác dính trước '$DAT,' (hay gặp sau reset) -> cắt bỏ phần rác, gói vẫn phải qua checksum
  - t_us giảm, không phải tràn, seq không về gần 0 -> TS_DISCONTINUITY (mở phiên mới)
  - seq lùi (Δseq ≥ 32768) mà không phải reset    -> SEQ_OUT_OF_ORDER (bỏ gói)
  - seq trùng gói trước                           -> SEQ_DUPLICATE (bỏ gói)
  - adc = 0 hoặc 4095                             -> ADC_SATURATED (cảnh báo, gói vẫn giữ)

Nguyên tắc: KHÔNG sửa file raw. Parser chỉ đọc; mọi bất thường ghi ra errors.log.
Trục thời gian luôn lấy từ t_us của MCU, KHÔNG dùng time.time() của PC.
Không dùng regex: tách chuỗi bằng str.split để đủ nhanh cho luồng UART (> 100 000 dòng/s).

LƯU Ý: ví dụ trong sổ tay "$DAT,105,210000,2234,74*" có checksum sai — XOR thực là 0x4D.
Nếu firmware của Quang tính khác, chỉ cần sửa hàm xor_checksum().
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SEQ_MOD = 65536
TS_MOD = 2 ** 32
ADC_MAX = 4095
WRAP_MAX_STEP_US = 1_000_000        # bước t_us qua điểm tràn phải < 1 s mới coi là tràn thật
RESET_SEQ_MAX = 10                  # sổ tay: seq < 10 sau khi t_us lùi => MCU reset

# Mã lỗi — dòng bị loại
TRUNCATED = "TRUNCATED_LINE"
BAD_FORMAT = "BAD_FORMAT"
CORRUPTED = "CORRUPTED_PACKET"
# Mã lỗi — gói hợp lệ nhưng bất thường về thứ tự/thời gian
SEQ_DROP = "SEQ_DROP"
SEQ_DUP = "SEQ_DUPLICATE"
SEQ_OOO = "SEQ_OUT_OF_ORDER"
TS_WRAP = "TS_WRAP"
TS_DISC = "TS_DISCONTINUITY"
MCU_RESET = "NEW_SESSION_MCU_RESET"
ADC_SAT = "ADC_SATURATED"

REJECT_CODES = (TRUNCATED, BAD_FORMAT, CORRUPTED)
ALL_CODES = (TRUNCATED, BAD_FORMAT, CORRUPTED, SEQ_DROP, SEQ_DUP, SEQ_OOO,
             TS_WRAP, TS_DISC, MCU_RESET, ADC_SAT)


def xor_checksum(payload: str) -> int:
    """XOR từng byte ASCII của payload (vd. "DAT,105,210000,2234" -> 0x4D)."""
    x = 0
    for b in payload.encode("ascii"):
        x ^= b
    return x


def format_line(seq: int, t_us: int, adc: int) -> str:
    """Tạo 1 dòng protocol_v1 hợp lệ (dùng cho mô phỏng & test)."""
    payload = f"DAT,{seq % SEQ_MOD},{t_us % TS_MOD},{int(adc)}"
    return f"${payload},{xor_checksum(payload):02X}*\r\n"


@dataclass
class Packet:
    """Một gói hợp lệ đã qua kiểm tra định dạng và checksum."""
    seq: int
    t_us: int
    adc: int


@dataclass
class ParseError:
    """Một dòng trong errors.log: số dòng trong file/luồng, mã lỗi, chi tiết."""
    line_no: int
    code: str
    detail: str

    def to_log(self) -> str:
        return f"line {self.line_no}: {self.code} | {self.detail}"


def _is_uint(s: str) -> bool:
    return 0 < len(s) <= 10 and s.isascii() and s.isdigit()


def parse_line(line: str) -> Packet | tuple[str, str]:
    """Kiểm tra 1 dòng. Trả về Packet nếu hợp lệ, ngược lại (mã_lỗi, chi_tiết). Không bao giờ ném lỗi."""
    s = line.strip("\r\n")
    if not s.startswith("$DAT,"):
        k = s.rfind("$DAT,")
        if k > 0 and s.endswith("*"):
            s = s[k:]                    # đồng bộ lại: bỏ byte rác trước '$DAT,' (thường gặp sau reset)
        else:
            return TRUNCATED, repr(s[:60])
    if not s.endswith("*"):
        return TRUNCATED, repr(s[:60])
    if not s.isascii():
        return BAD_FORMAT, "có ký tự không phải ASCII: " + repr(s[:60])
    body = s[1:-1]                       # bỏ '$' và '*'
    parts = body.split(",")
    if len(parts) != 5:
        return BAD_FORMAT, f"{len(parts)} trường (cần 5): " + repr(s[:60])
    _, seq_s, t_s, adc_s, chk_s = parts
    if not (_is_uint(seq_s) and _is_uint(t_s) and _is_uint(adc_s)):
        return BAD_FORMAT, "trường số không hợp lệ: " + repr(s[:60])
    if len(chk_s) != 2 or any(c not in "0123456789abcdefABCDEF" for c in chk_s):
        return BAD_FORMAT, "chk không phải 2 chữ số hex: " + repr(chk_s)
    seq, t_us, adc = int(seq_s), int(t_s), int(adc_s)
    if not (seq < SEQ_MOD and t_us < TS_MOD and adc <= ADC_MAX):
        return BAD_FORMAT, f"giá trị ngoài miền: seq={seq} t_us={t_us} adc={adc}"
    chk_rx = int(chk_s, 16)
    chk_calc = xor_checksum(body.rsplit(",", 1)[0])
    if chk_calc != chk_rx:
        return CORRUPTED, f"chk nhận {chk_rx:02X} ≠ tính {chk_calc:02X}"
    return Packet(seq, t_us, adc)


@dataclass
class Session:
    """Một phiên đo liên tục: trục thời gian đơn điệu tăng, không chứa reset."""
    seq: list = field(default_factory=list)
    t_us_unwrapped: list = field(default_factory=list)
    adc: list = field(default_factory=list)
    dropped: int = 0
    start_line: int = 0

    @property
    def t_s(self) -> np.ndarray:
        t = np.asarray(self.t_us_unwrapped, dtype=np.float64)
        return (t - t[0]) * 1e-6 if t.size else t

    @property
    def adc_array(self) -> np.ndarray:
        return np.asarray(self.adc, dtype=np.float64)

    def __len__(self):
        return len(self.adc)


class StreamParser:
    """Parser có trạng thái: nhận từng dòng (UART thật hoặc replay), không bao giờ crash."""

    def __init__(self):
        self.sessions: list[Session] = [Session(start_line=1)]
        self.errors: list[ParseError] = []
        self.n_lines = 0
        self.n_valid = 0
        self._prev: Packet | None = None
        self._wrap_offset = 0
        self._line_no = 0

    @property
    def current(self) -> Session:
        return self.sessions[-1]

    def _err(self, code, detail):
        self.errors.append(ParseError(self._line_no, code, detail))

    def _new_session(self):
        if len(self.current) == 0:
            self.current.start_line = self._line_no
        else:
            self.sessions.append(Session(start_line=self._line_no))
        self._wrap_offset = 0

    def feed(self, line: str, line_no: int | None = None) -> Packet | None:
        """Xử lý 1 dòng. Trả về Packet nếu được nhận vào phiên hiện tại, ngược lại None.

        line_no: số dòng thật trong file (để errors.log trỏ đúng chỗ); mặc định = thứ tự dòng đã nhận.
        """
        self.n_lines += 1
        self._line_no = line_no if line_no is not None else self.n_lines
        try:
            res = parse_line(line)
        except Exception as e:                       # lưới an toàn: dòng rác không làm sập parser
            res = (BAD_FORMAT, f"{type(e).__name__}: {e}")
        if not isinstance(res, Packet):
            self._err(*res)
            return None
        p = res
        prev = self._prev
        if prev is not None:
            dseq = (p.seq - prev.seq) % SEQ_MOD
            if p.t_us < prev.t_us:
                step = (p.t_us - prev.t_us) % TS_MOD
                if step <= WRAP_MAX_STEP_US and 0 < dseq < SEQ_MOD // 2:
                    self._wrap_offset += TS_MOD
                    self._err(TS_WRAP, f"t_us {prev.t_us}->{p.t_us}, cộng 2^32")
                elif p.seq < RESET_SEQ_MAX:
                    self._err(MCU_RESET, f"t_us {prev.t_us}->{p.t_us}, seq {prev.seq}->{p.seq}: mở phiên mới")
                    self._new_session()
                    prev = None
                elif dseq == 0 or dseq >= SEQ_MOD // 2:
                    pass                                 # gói cũ gửi lại: xử lý ở SEQ_DUP / SEQ_OUT_OF_ORDER
                else:
                    self._err(TS_DISC, f"t_us lùi {prev.t_us}->{p.t_us} (seq {prev.seq}->{p.seq}): mở phiên mới")
                    self._new_session()
                    prev = None
            elif dseq >= SEQ_MOD // 2 and p.seq < RESET_SEQ_MAX:
                self._err(MCU_RESET, f"seq {prev.seq}->{p.seq}, t_us {prev.t_us}->{p.t_us}: mở phiên mới")
                self._new_session()
                prev = None
            if prev is not None:
                if dseq == 0:
                    self._err(SEQ_DUP, f"seq {p.seq} lặp: bỏ gói")
                    return None
                if dseq >= SEQ_MOD // 2:
                    self._err(SEQ_OOO, f"seq lùi {prev.seq}->{p.seq}: bỏ gói")
                    return None
                if dseq > 1:
                    lost = dseq - 1
                    self.current.dropped += lost
                    self._err(SEQ_DROP, f"seq {prev.seq}->{p.seq}: mất {lost} mẫu")
        if p.adc in (0, ADC_MAX):
            self._err(ADC_SAT, f"adc={p.adc} chạm biên")
        s = self.current
        s.seq.append(p.seq)
        s.t_us_unwrapped.append(p.t_us + self._wrap_offset)
        s.adc.append(p.adc)
        self._prev = p
        self.n_valid += 1
        return p

    def counts(self) -> Counter:
        """Số lần xuất hiện của từng mã lỗi."""
        return Counter(e.code for e in self.errors)

    def summary(self) -> dict:
        """Tổng kết: tách bạch 'dòng bị loại' với 'mẫu bị mất'."""
        c = self.counts()
        return {
            "lines_total": self.n_lines,
            "packets_valid": self.n_valid,
            "lines_rejected": sum(c[k] for k in REJECT_CODES),
            **{k: c[k] for k in ALL_CODES},
            "samples_lost": sum(s.dropped for s in self.sessions),
            "sessions": len([s for s in self.sessions if len(s)]),
        }

    def write_errors(self, path: str | Path, source: str = ""):
        """Ghi errors.log: mỗi dòng 'line N: MÃ | chi tiết', cuối file là bảng đếm."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# errors.log — parser protocol_v1{(' — nguồn: ' + source) if source else ''}"]
        lines += [e.to_log() for e in self.errors]
        lines.append("# ---- tổng kết ----")
        lines += [f"# {k} = {v}" for k, v in self.summary().items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_file(path: str | Path) -> StreamParser:
    """Đọc file raw (chỉ đọc, không ghi đè). Bỏ qua dòng metadata '#' và dòng trống.

    Đọc ở chế độ nhị phân rồi giải mã từng dòng để byte rác không làm hỏng việc đọc file.
    """
    sp = StreamParser()
    with open(path, "rb") as f:
        for i, raw in enumerate(f, start=1):
            line = raw.decode("ascii", errors="replace")
            if line.startswith("#") or not line.strip():
                continue
            sp.feed(line, line_no=i)
    return sp


# ---- Chính sách mất mẫu --------------------------------------------------------------
@dataclass
class GapReport:
    n_interpolated: int
    invalid_gaps: list            # [(t_start_s, t_end_s), ...]

    @property
    def invalid(self) -> bool:
        return len(self.invalid_gaps) > 0


def apply_drop_policy(t_s: np.ndarray, x: np.ndarray, fs: float,
                      interp_max_gap_s: float = 0.0045, invalid_gap_s: float = 0.010):
    """Mất 1 mẫu lẻ (Δt ≤ ~4 ms) -> nội suy tuyến tính. Khoảng > invalid_gap_s -> INVALID_GAP.

    Trả về (t_new, x_new, segment_id, GapReport). segment_id tăng sau mỗi khoảng trống lớn,
    để bộ tích phân KHÔNG nối xuyên qua khoảng mất mẫu.
    """
    t_s = np.asarray(t_s, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    dt_nom = 1.0 / fs
    t_out, x_out, seg_out = [t_s[0]], [x[0]], [0]
    seg, n_interp, gaps = 0, 0, []
    for i in range(1, t_s.size):
        dt = t_s[i] - t_s[i - 1]
        if dt > invalid_gap_s:
            gaps.append((float(t_s[i - 1]), float(t_s[i])))
            seg += 1
        elif dt > 1.5 * dt_nom and dt <= interp_max_gap_s:
            n_missing = int(round(dt / dt_nom)) - 1
            for j in range(1, n_missing + 1):
                tj = t_s[i - 1] + j * dt / (n_missing + 1)
                t_out.append(tj)
                x_out.append(x[i - 1] + (x[i] - x[i - 1]) * (tj - t_s[i - 1]) / dt)
                seg_out.append(seg)
                n_interp += 1
        elif dt > interp_max_gap_s:
            # 4.5–10 ms: không nội suy, nhưng cũng chưa INVALID — chỉ ghi nhận
            gaps.append((float(t_s[i - 1]), float(t_s[i])))
            seg += 1
        t_out.append(t_s[i])
        x_out.append(x[i])
        seg_out.append(seg)
    rep = GapReport(n_interpolated=n_interp,
                    invalid_gaps=[g for g in gaps if g[1] - g[0] > invalid_gap_s])
    return np.array(t_out), np.array(x_out), np.array(seg_out), rep
