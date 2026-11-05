# Data Schema và giao thức UART – Smart Spirometer

| Mục | Nội dung |
| --- | --- |
| Gói việc | VIET-01 – Chốt chuỗi tính toán và giao thức |
| Phiên bản schema | v1.0-draft (đề xuất của Việt, **Quang quyết định cuối**) |
| Người viết | Việt |
| Người kiểm tra | Quang |
| Trạng thái | Chờ kiểm tra. Mọi mục đánh dấu CẦN XÁC MINH là đề xuất, chưa phải quyết định |

Mục đích: thống nhất định dạng dữ liệu từ STM32 lên Python để parser phát hiện được mất mẫu, lỗi truyền và reset mà không phải đoán.

---

## 1. Nguyên tắc

1. STM32 gửi **ADC thô**. Python tính zero, điện áp, ΔP. Lý do: dễ kiểm tra lại, dữ liệu raw giữ nguyên giá trị gốc.
2. Mỗi mẫu có số thứ tự và thời gian riêng, nên khi mất mẫu vẫn tính tích phân đúng.
3. Không nội suy âm thầm. Mất mẫu thì đánh cờ và báo.
4. File raw không bao giờ bị ghi đè; mỗi phiên kèm file config.

## 2. Khung truyền

**Giai đoạn bring-up (đề xuất):** văn bản, một mẫu một dòng, phân cách bằng dấu phẩy, kết thúc bằng `\n`. Dễ xem bằng terminal.

```
seq,timestamp_us,adc_raw,flags\n
```

| Thuộc tính | Đề xuất | Trạng thái |
| --- | --- | --- |
| Kiểu | Text CSV, ASCII | CẦN XÁC MINH với Quang |
| Kết thúc dòng | `\n` | CẦN XÁC MINH |
| Có dòng header đầu phiên | Có, dòng `#CFG` (xem mục 5) | CẦN XÁC MINH |
| CRC/checksum | Chưa dùng ở giai đoạn text; xem xét khi chuyển binary | **CHƯA CHỐT** |
| Baudrate | 115200 (8N1) | CẦN XÁC MINH |
| Sample rate `fs` | 100 Hz là mức tối thiểu đề xuất; cân nhắc ≥ 200 Hz | **CHƯA CHỐT** |

**Kiểm tra băng thông (ước lượng):** 115200 baud 8N1 cho khoảng 11520 byte/s. Một dòng text khoảng 25 byte.

| fs | Byte/s (≈25 B/dòng) | Nhận xét |
| --- | --- | --- |
| 100 Hz | ≈ 2500 | Dư |
| 200 Hz | ≈ 5000 | Dư |
| 500 Hz | ≈ 12500 | **Vượt** 115200 baud; cần binary hoặc tăng baud |

Lý do cân nhắc fs cao hơn: đỉnh lưu lượng tăng rất nhanh nên fs thấp có thể làm tròn đỉnh. Con số thật cần đánh giá bằng dữ liệu (Tuần 3, 4).

**Giai đoạn sau (tùy chọn):** chuyển sang binary có header, độ dài và CRC16 khi cần fs cao. Nếu chuyển, cập nhật schema thành v2 và giữ nguyên tên trường.

## 3. Trường dữ liệu

| Trường | Kiểu | Đơn vị | Ý nghĩa |
| --- | --- | --- | --- |
| `seq` | uint32 | mẫu | Tăng 1 sau mỗi mẫu; Python dùng để phát hiện mất mẫu |
| `timestamp_us` | uint32 | µs | Thời điểm lấy mẫu theo timer MCU; dùng tính dt cho tích phân |
| `adc_raw` | uint16 | count | Mã ADC thô, chưa quy đổi |
| `flags` | uint8 | bit | Cờ trạng thái/chất lượng (xem mục 4) |

Ghi chú:
- `timestamp_us` kiểu uint32 **tràn sau khoảng 71,6 phút** (2^32 µs). Quy định: khi timestamp giảm mà seq vẫn liên tục thì Python xử lý wrap; nếu seq cũng về 0 thì xem là phiên mới. **CẦN XÁC MINH** với Quang.
- `adc_raw`: độ phân giải 12 bit (0–4095) **hay** 16 bit hiệu dụng do oversampling. **CẦN XÁC MINH** với Quang; ghi vào `#CFG` để Python không phải đoán.
- Ưu tiên lấy mẫu bằng timer kích ADC (khoảng thời gian cố định), để `timestamp_us` phản ánh đúng thời điểm lấy mẫu chứ không phải thời điểm gửi.

## 4. Cờ `flags` (đề xuất, chọn theo bit)

| Bit | Mask | Ý nghĩa |
| --- | --- | --- |
| 0 | `0x01` | Clipping (ADC chạm trần hoặc đáy) |
| 1 | `0x02` | Lỗi phần cứng / mất kết nối cảm biến |
| 2 | `0x04` | Overrun / mất mẫu phía MCU |
| 3 | `0x08` | Vừa reset MCU |
| 4 | `0x10` | Đang trong chế độ zero |
| 5–7 | | Dự trữ |

`flags = 0x00` nghĩa là bình thường. Các bit có thể bật đồng thời (ví dụ `0x03` = clipping và lỗi phần cứng). Danh sách bit là **đề xuất**, Quang chốt.

Ngưỡng phát hiện clipping (bao nhiêu mã tính là chạm trần/đáy): **CHƯA CHỐT**.

## 5. Bản tin cấu hình đầu phiên

Đầu mỗi phiên, MCU gửi một dòng cấu hình để Python lưu cùng file raw:

```
#CFG,fs=200,bits=12,vref_mv=3300,fw=0.1.0,divider=1.5
```

| Khóa | Ý nghĩa |
| --- | --- |
| `fs` | Tần số lấy mẫu (Hz) |
| `bits` | Số bit ADC (hoặc bit hiệu dụng nếu oversampling) |
| `vref_mv` | Vref theo mV |
| `fw` | Phiên bản firmware |
| `divider` | Hệ số chia áp (nếu MCU biết), nếu không thì Python lấy từ file cấu hình |

Python ghi các giá trị này vào file `*_config.json` đi kèm file raw. Các giá trị chưa được Nhung/Quang xác nhận ghi rõ CẦN XÁC MINH trong config.

## 6. Quy tắc parser (Python)

| Tình huống | Hành vi |
| --- | --- |
| `seq` nhảy (seq hiện tại ≠ seq trước + 1) | Đánh cờ mất mẫu, ghi số mẫu mất vào log; **không nội suy** |
| `seq` về 0 hoặc nhỏ hơn đáng kể | Bắt đầu phiên mới; không ghép với phiên trước |
| `timestamp_us` không tăng (khi seq hợp lệ) | Cảnh báo; nếu là wrap thì xử lý theo mục 3 |
| Dòng sai định dạng / thiếu trường | Bỏ dòng, tăng bộ đếm lỗi, ghi log |
| Có cờ `flags` ≠ 0 | Chuyển cờ sang cột chất lượng; không tự xóa mẫu |
| Đoạn dữ liệu có lỗi | Gắn nhãn đoạn đó; **không** nối thành một lần đo hoàn chỉnh |

Dữ liệu thô và dữ liệu đã xử lý để ở hai chỗ khác nhau (`data/raw/`, `data/processed/`). Không ghi đè raw.

## 7. Ví dụ (minh họa định dạng, không phải số đo)

```
# EXAMPLE ONLY - not measured data
#CFG,fs=200,bits=12,vref_mv=3300,fw=0.1.0,divider=1.5
0,0,2068,0
1,5000,2069,0
2,10000,2067,0
```

Ví dụ ca mất mẫu (seq nhảy từ 2 sang 5), parser phải ghi "mất 2 mẫu":

```
# EXAMPLE ONLY - not measured data
2,10000,2067,0
5,25000,2070,0
```

## 8. Nhận dạng dữ liệu tổng hợp

Dữ liệu mô phỏng luôn có nhãn trong tên file (`*_synthetic_*`) và trong `#CFG` (`source=synthetic`). Không để lẫn với dữ liệu đo thật.

## 9. Chờ xử lý (cần Quang)

| # | Câu hỏi | Trạng thái |
| --- | --- | --- |
| 1 | Sample rate cuối cùng; có cố định bằng timer không | CHỜ XỬ LÝ |
| 2 | ADC 12 bit hay có oversampling; Vref thực | CHỜ XỬ LÝ |
| 3 | Text hay binary; baudrate; có CRC không | CHỜ XỬ LÝ |
| 4 | Danh sách bit `flags` và ngưỡng clipping | CHỜ XỬ LÝ |
| 5 | Có gửi `#CFG` đầu phiên không | CHỜ XỬ LÝ |
| 6 | Cách xử lý tràn `timestamp_us` | CHỜ XỬ LÝ |
| 7 | Thời gian lấy mẫu ADC (sampling time) phù hợp với trở nguồn của mạch chia áp 10k/20k | CHỜ XỬ LÝ (hỏi cả Nhung) |