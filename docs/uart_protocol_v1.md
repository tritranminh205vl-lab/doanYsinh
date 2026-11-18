# Đặc tả giao thức UART protocol_v1 — bản đối chiếu Firmware ↔ Python

Người soạn: Nguyễn Hoàng Việt (phía Python) · Gửi: Vũ Đình Quang (firmware) · Ngày: 06/11/2026
Mã Python tương ứng: `software/parser.py` (hàm `parse_line`, `xor_checksum`, `StreamParser.feed`).

Mục đích: Quang đọc từng mục, đánh dấu **Khớp / Khác** so với firmware hiện tại. Mục nào khác
thì ghi cách firmware đang làm vào cột "Firmware thực tế" — Python sẽ sửa theo, không cần Quang đổi.

## 1. Lớp vật lý

| Mục | Python đang giả định | Firmware thực tế | Khớp? |
|---|---|---|---|
| Vi điều khiển | STM32F103C8T6 (theo BOM của Nhung) | | |
| Cổng | USART1: PA9 = TX, PA10 = RX, qua CP2102 | | |
| Baud | 230400 | | |
| Khung bit | 8 data, no parity, 1 stop (8N1) | | |
| Tốc độ gửi | 500 dòng/giây (1 dòng = 1 mẫu ADC) | | |
| Kênh ADC | ADC1 kênh 0 (PA0), 12 bit, Vref = 3.3 V | | |

Băng thông: dòng dài nhất 32 byte × 500 dòng/s = 16 000 byte/s ≈ 69 % của 23 040 byte/s (230400 8N1).

## 2. Khung bản tin

```
$DAT,<seq>,<t_us>,<adc_raw>,<chk>*\r\n
```

| Trường | Kiểu | Miền giá trị | Định dạng in | Firmware thực tế | Khớp? |
|---|---|---|---|---|---|
| `$DAT,` | tiền tố cố định | — | đúng 5 ký tự `$DAT,` | | |
| `seq` | uint16 | 0–65535, sau 65535 về 0 | thập phân, **không** đệm số 0 | | |
| `t_us` | uint32 | 0–4 294 967 295 µs | thập phân, không đệm | | |
| `adc_raw` | uint16 | 0–4095 | thập phân, không đệm | | |
| `chk` | uint8 | 00–FF | **đúng 2** chữ số hex (Python nhận cả hoa lẫn thường) | | |
| `*\r\n` | hậu tố | — | `*` rồi CR LF (Python cũng nhận chỉ `\n`) | | |

Không có khoảng trắng ở bất kỳ đâu trong dòng.

## 3. Checksum

```
chk = XOR của từng byte ASCII trong chuỗi  "DAT,<seq>,<t_us>,<adc_raw>"
      (KHÔNG gồm '$', KHÔNG gồm dấu phẩy ngay trước chk, KHÔNG gồm '*')
```

Mã C tham chiếu (Quang so với code firmware):

```c
char payload[32];
int n = snprintf(payload, sizeof payload, "DAT,%u,%lu,%u",
                 (unsigned)seq, (unsigned long)t_us, (unsigned)adc);
uint8_t chk = 0;
for (int i = 0; i < n; i++) chk ^= (uint8_t)payload[i];
static char line[40];          /* static: buffer phải còn sống đến khi DMA gửi xong */
int len = snprintf(line, sizeof line, "$%s,%02X*\r\n", payload, chk);
/* gửi len byte của line qua USART1 (DMA hoặc hàng đợi); không gửi blocking trong ngắt 2 ms */
```

**Câu hỏi:** sổ tay in ví dụ `$DAT,105,210000,2234,74*`, nhưng XOR đúng theo quy tắc trên là `4D`.
Firmware ra `74` hay `4D` cho dòng này? Nếu ra số khác, firmware đang tính trên đoạn nào?

## 4. Dòng mẫu chuẩn (test vector)

Firmware in đúng **từng byte** các dòng sau với cùng (seq, t_us, adc) là khớp:

| seq | t_us | adc | Dòng phải gửi | Số byte |
|---|---|---|---|---|
| 0 | 0 | 2068 | `$DAT,0,0,2068,71*\r\n` | 19 |
| 105 | 210000 | 2234 | `$DAT,105,210000,2234,4D*\r\n` | 26 |
| 1 | 2000 | 0 | `$DAT,1,2000,0,7E*\r\n` | 19 |
| 12345 | 123456789 | 2100 | `$DAT,12345,123456789,2100,7E*\r\n` | 31 |
| 65535 | 4294967295 | 4095 | `$DAT,65535,4294967295,4095,48*\r\n` | 32 |

## 5. Nhãn thời gian t_us (quan trọng với F103)

| Mục | Python đang giả định | Firmware thực tế | Khớp? |
|---|---|---|---|
| Ý nghĩa | thời điểm **lấy mẫu ADC** (trong ngắt timer/ADC), không phải lúc gửi UART | | |
| Bước giữa 2 mẫu | 2000 µs (500 Hz, kích bằng timer phần cứng) | | |
| Tràn | đúng tại 2^32 µs ≈ 71.58 phút, rồi về 0 | | |

STM32F103 **không có timer 32 bit**. Cần ghép timer 16 bit chạy 1 MHz + biến đếm tràn để ra
uint32 µs. **Không** dùng `DWT->CYCCNT / 72`: giá trị này tràn sau 2^32 / 72 MHz ≈ 59.65 s chứ
không phải 2^32 µs, và Python sẽ dựng sai trục thời gian.

## 6. Hành vi đặc biệt

| Tình huống | Firmware nên làm | Python xử lý | Firmware thực tế |
|---|---|---|---|
| Khởi động / reset MCU | seq bắt đầu lại từ 0, t_us từ giá trị nhỏ | t_us lùi + seq < 10 → mở phiên đo mới | |
| ADC chạm 0 hoặc 4095 | gửi bình thường | ghi cảnh báo ADC_SATURATED, giữ mẫu | |
| Buffer UART đầy | bỏ cả dòng, **không** gửi nửa dòng | dòng cụt → TRUNCATED_LINE; thiếu seq → SEQ_DROP | |
| Gửi lại gói cũ | không làm | seq trùng/lùi → bỏ gói | |
| Dòng khác (log debug, banner khởi động) | không gửi trên cùng UART, hoặc bắt đầu bằng `#` | dòng `#` bị bỏ qua; dòng khác → lỗi định dạng | |

## 7. Nhờ Quang gửi lại

1. Bảng trên đã điền cột "Firmware thực tế".
2. File `sample_stream.csv`: thu thẳng từ bo ít nhất 30 giây (≈ 15 000 dòng), mở cổng COM ở 230400,
   lưu nguyên văn, không sửa. Có đoạn để yên và đoạn thổi nhẹ vào ống.
3. Nếu được: thêm một file thu qua một lần nhấn nút reset bo, để kiểm tra phần tách phiên.

Phía Python kiểm tra bằng:
```
python scripts/parser_demo.py --file data/sample/sample_stream.csv
```
Kết quả mong đợi: `CORRUPTED_PACKET = 0`, `TRUNCATED_LINE ≈ 0`, `samples_lost / packets_valid < 0.1 %`.
