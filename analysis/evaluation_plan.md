# Kế hoạch đánh giá sai số, trễ lọc và drift – Smart Spirometer

| Mục | Nội dung |
| --- | --- |
| Gói việc | VIET-01 – Chốt chuỗi tính toán và giao thức |
| Phiên bản | v1 (bản bàn giao Tuần 1) |
| Người viết | Việt |
| Người kiểm tra | Quang |
| Trạng thái | Chờ kiểm tra. Mọi số liệu trong tài liệu này là **tính toán theo giả định**, không phải số đo |

---

## 1. Mục tiêu đồ án và chuẩn lâm sàng

| Khía cạnh | Nội dung |
| --- | --- |
| Mục tiêu đồ án | Xây dựng và đánh giá chuỗi xử lý tín hiệu cho thiết bị đo lưu lượng khí thở chi phí thấp, kèm số liệu sai số, độ lặp lại, trễ và drift trong dải đã thử |
| Chuẩn lâm sàng | Chỉ dùng để **tham khảo**, không tuyên bố tuân thủ. Mọi ngưỡng số của chuẩn là **CẦN XÁC MINH** cho đến khi có văn bản gốc |
| Giới hạn | Thiết bị và phần mềm là mô hình học thuật, không phải thiết bị chẩn đoán đã kiểm định. Thử trên người chỉ khi quy trình đã được người hướng dẫn kiểm tra |

Nguyên tắc báo cáo: không suy độ chính xác ra ngoài dải đã thử; không dùng số tổng hợp (mô phỏng) làm số đo.

## 2. Độ phân giải của hệ đo (tính theo giả định)

**Giả định cần xác nhận** (CHỜ XỬ LÝ với Quang, Nhung): ADC 12 bit, Vref = 3,3 V, chia áp 10 kΩ/20 kΩ (hệ số ×1,5 ngược), độ nhạy cảm biến S = 1 V/kPa, V_zero ≈ 2,5 V. S và V_zero danh định đã đối chiếu với datasheet MPXV7002 Rev. 5 (Table 5 tr. 4, Fig. 7 tr. 6). ADC, Vref, chia áp vẫn chờ xác nhận. Đối chiếu STM32G030 trước khi dùng các số dưới đây trong báo cáo.

| Đại lượng | Công thức | Giá trị (theo giả định) |
| --- | --- | --- |
| LSB tại ADC | Vref / 2^N | ≈ 0,806 mV |
| LSB tại cảm biến | LSB_adc × 1,5 | ≈ 1,21 mV |
| Phân giải ΔP | LSB_sensor / S | ≈ 1,2 Pa/LSB |
| Mã ADC khi ΔP = 0 | (V_zero / 1,5) / LSB_adc | ≈ 2069 (danh định; thực tế lệch, xem 2b) |
| Dải mã ứng với ±2 kPa | (0,5 V → 4,5 V) / 1,5 / LSB_adc | ≈ 414 đến ≈ 3724 |
| Nhiễu lượng tử lý tưởng | LSB / √12 | ≈ 0,29 LSB |

Hệ quả cần ghi trong báo cáo: nếu Q tăng theo căn bậc hai của ΔP thì ở lưu lượng thấp, một bước 1,2 Pa chiếm tỉ lệ lớn so với tín hiệu. Điều này ảnh hưởng đến độ chính xác của đoạn cuối lần thở (FVC). Kiểm chứng bằng dữ liệu ở Tuần 4–5.

Ghi chú: do cảm biến theo tỉ lệ với nguồn 5 V còn ADC theo Vref 3,3 V, trôi của hai nguồn làm zero trôi. Cần đo ở mục drift (mục 3).

## 2b. Sai số của cảm biến theo datasheet (tính theo giả định)

Nguồn: NXP MPXV7002 Rev. 5, Table 5 và chú thích [6], [7] (tr. 4). Điều kiện: Vs = 5,0 V, 10–60 °C, **giả định đã auto-zero và nhiệt độ lệch tối đa ±5 °C giữa lúc zero và lúc đo**.

| Thông số | Giá trị | Quy ra Pa (S = 1 V/kPa) | Quy ra LSB (≈ 1,21 mV/LSB tại cảm biến) |
| --- | --- | --- | --- |
| Độ chính xác typ | ±2,5 % VFSS (VFSS typ 4,0 V → ±0,10 V) | ±100 Pa | ≈ ±83 LSB |
| Độ chính xác max | ±6,25 % VFSS (→ ±0,25 V) | ±250 Pa | ≈ ±207 LSB |
| Dung sai offset (suy ra từ Voff 0,25–0,75 V) | ±0,25 V so với danh định | ±250 Pa | ≈ ±207 LSB |
| Thời gian đáp ứng | 1,0 ms (10–90 %) | — | — |

Hệ quả cần ghi trong báo cáo:

1. Sai số **cảm biến** (hàng chục đến vài trăm Pa theo thông số datasheet) lớn hơn nhiều so với sai số **lượng tử hóa ADC** (≈ 1,2 Pa/LSB). Độ phân giải ADC không phải yếu tố giới hạn; zero và độ chính xác cảm biến mới là yếu tố giới hạn.
2. Datasheet nêu độ chính xác là **ngân sách sai số gồm nhiều thành phần** (tuyến tính, trễ nhiệt, trễ áp, TcSpan, TcOffset, sai lệch danh định) mà không tách riêng. Phần nào mất đi sau khi Zero thì datasheet không cho biết; cần đo (T2, T3, T7).
3. Nhiệt độ lệch hơn ±5 °C giữa lúc Zero và lúc đo, hoặc ngoài 10–60 °C, thì độ chính xác đã nêu không còn đảm bảo. Ghi nhiệt độ môi trường khi thu nếu có thể.
4. Datasheet dựa trên không khí khô. Hơi thở ẩm có thể ảnh hưởng hiệu năng và độ bền; thử bàn ban đầu nên dùng nguồn khí khô (bơm/syringe) trước.

## 3. Bảng phép thử

| # | Phép thử | Đo gì | Tham chiếu | Cách làm | Tuần |
| --- | --- | --- | --- | --- | --- |
| T1 | Độ phân giải | LSB → V → Pa | Công thức (mục 2) | Tính từ Vref, chia áp, S; kiểm chứng bằng thực nghiệm | 1 (tính), 4 (kiểm) |
| T2 | Nhiễu tại zero | σ của `adc_raw` (LSB, Pa) | Không dòng khí | Thu vài giây, lặp nhiều lần; so σ với 0,29 LSB lý tưởng để biết nhiễu analog/nguồn có trội không | 4 |
| T3 | Drift zero | Trôi V_zero theo thời gian | Không dòng khí | Thu 5–10 phút, vẽ V_zero(t); ghi nhiệt độ/điều kiện nếu có | 4 |
| T4 | Chiều ΔP | Dấu ΔP khi thổi vào / hút ra | Quy ước đã chốt | Thử bàn cùng Nhung; ghi ảnh và log | 4 |
| T5 | Trễ lọc | Trễ giữa tín hiệu đã lọc và tín hiệu gốc | Tín hiệu tổng hợp | Cross-correlation; **ghi riêng online và offline** | 3 |
| T6 | Ảnh hưởng offset tới thể tích | ΔV = Q_off × T | Mô phỏng | Quét offset và thời gian thu; vẽ đồ thị | 3 |
| T7 | Sai số thể tích | (V_đo − V_chuẩn) / V_chuẩn | Bơm/syringe thể tích chuẩn của Trí | Nhiều lượt; tách tập fit và tập kiểm chứng | 5 |
| T8 | Sai số PEF | (PEF_đo − PEF_chuẩn) / PEF_chuẩn | **CẦN XÁC MINH** có nguồn lưu lượng chuẩn Q(t) hay không | Chỉ tính khi có tham chiếu tương ứng | 5 |
| T9 | Độ lặp lại | σ và hệ số biến thiên (CV) giữa các lượt | Không cần tham chiếu | Lặp N lượt cùng điều kiện, ghi N | 5 |
| T10 | Chất lượng dữ liệu | Số mẫu mất, số khung lỗi | Seq và timestamp | Thử rút dây, ép clipping; kiểm tra cờ | 4 |

Mỗi phép thử lưu đủ **ba thứ**: dữ liệu (CSV), ảnh (plot) và log. Phép thử thiếu đầu vào ghi **Chờ xử lý** và báo Trí. Không tự điền kết quả dự kiến thành số đo.

## 4. Đánh giá offset và drift

**Ví dụ minh họa (tính tay, không phải số đo):** giả sử offset lưu lượng là 0,02 L/s kéo dài 6 s, sai số thể tích tích lũy là

ΔV = Q_off × T = 0,02 × 6 = 0,12 L

Offset nhỏ không đổi cộng dồn thành sai số thể tích tăng tuyến tính theo thời gian thu. Đây là lý do:

- **Không** cắt giá trị âm về 0 (clip) để che drift. Cắt âm làm sai số lệch một chiều, khó nhận ra và khó hiệu chỉnh.
- Zero phải được đo ngay trước mỗi lần thu và lưu cùng dữ liệu.
- Mô phỏng ở Tuần 3 quét offset và thời gian thu để lập đồ thị ΔV theo (Q_off, T).

## 5. Ngân sách độ trễ

Tổng trễ = trễ analog + trễ lọc số + trễ truyền.

| Thành phần | Cách xác định | Trạng thái |
| --- | --- | --- |
| Trễ analog (lọc RC) | τ = R × C, fc = 1/(2πRC); dùng đáp ứng bước | **CHỜ XỬ LÝ**: cần giá trị R, C từ Nhung |
| Trễ lọc số | Đo bằng T5 (cross-correlation) | Tuần 3 |
| Trễ cảm biến | Thời gian đáp ứng 10–90 % = 1,0 ms (typ), datasheet tr. 4 | Đã có số danh định; kiểm chứng ở bàn thử |
| Trễ truyền/đệm | Từ fs, khung UART, đệm queue | CHỜ XỬ LÝ: cần fs, baudrate từ Quang |

Quy tắc: lọc cần dữ liệu tương lai (lọc zero-phase) **không** được báo là "trễ bằng 0" cho ứng dụng thời gian thực. Báo cáo tách hai bảng: **online** (nhân quả) và **offline**.

Có thể mô phỏng chia áp + RC bằng LTspice (`.ac` để lấy fc, `.tran` để lấy đáp ứng bước) rồi đối chiếu với mô hình Python, nhưng giá trị R, C thật phải do Nhung xác nhận.

## 6. Quy tắc quản lý dữ liệu

1. File dữ liệu thô chỉ ghi thêm, **không ghi đè**.
2. Mỗi lần thu có file cấu hình đi kèm (fs, N, Vref, hệ số chia, phiên bản firmware, phiên bản phần mềm).
3. Dữ liệu thô và dữ liệu xử lý để riêng.
4. Dữ liệu mô phỏng có nhãn `synthetic` trong tên file và metadata.
5. Mỗi phép thử lưu: dữ liệu (csv), ảnh (plot), log.
6. Loại điểm dữ liệu phải ghi lý do.
7. Mọi giá, dung sai và tiêu chuẩn chưa có căn cứ ghi **CẦN XÁC MINH**.

## 7. Chờ xử lý

| # | Cần ai | Nội dung | Trạng thái |
| --- | --- | --- | --- |
| 1 | Quang | fs, N, Vref, baudrate cuối cùng | CHỜ XỬ LÝ |
| 2 | Nhung | R, C của lọc; độ ổn định nguồn | CHỜ XỬ LÝ |
| 3 | Trí | Có bơm/syringe thể tích chuẩn không; có nguồn lưu lượng chuẩn Q(t) không | CHỜ XỬ LÝ |
| 4 | Việt | S, V_zero: đã đối chiếu datasheet MPXV7002 Rev. 5. Còn lại: tra INL/DNL của ADC STM32G030 | MỘT PHẦN |
| 5 | Nhóm | Văn bản chuẩn lâm sàng gốc (nếu cần tham khảo ngưỡng) | CHƯA CÓ |