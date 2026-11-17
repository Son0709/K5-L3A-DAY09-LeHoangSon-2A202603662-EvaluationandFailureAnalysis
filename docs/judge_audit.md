# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, không gọi model; FAIL là lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt cả 3 | **Dùng** (kèm sửa rubric bên dưới) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Trượt κ và recall | **Loại** khỏi gate |

Ma trận nhầm lẫn (human × judge):

| Tiêu chí | tp | fp | fn | tn | Tỉ lệ FAIL quan sát | Sau Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 | 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 | 0.30 |

## ≥5 case audit thủ công (tone_ok)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã; judge coi suồng sã là thân thiện. Rubric thêm: "thân thiện" không gồm khẩu ngữ ("nha", "nhé" cuối câu, xưng "em/bạn") với khách. |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Giọng ra lệnh; judge chỉ thấy "Dạ, vui lòng". Rubric thêm: chấm cả câu, một cụm lịch sự không che được mệnh lệnh ("không cần nhắn thêm"). |
| 3 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa hoàn thêm ngoài kết quả hệ thống. Đây là lỗi nội dung, không phải giọng điệu: chuyển sang grader code đối chiếu ledger (FM-08), không đòi judge tone bắt. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý; judge phạt vì thiếu xin lỗi. Rubric ghi rõ: xin lỗi không bắt buộc khi hoàn tiền thành công. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | CS LogiX cho phép từ "refund"; judge phạt vì tiếng Anh. Rubric thêm danh sách thuật ngữ cho phép (refund). |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). Sửa nhãn trong tập hiệu chuẩn, không sửa rubric; tính lại κ sau khi sửa. |
| 7 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | Người | Dịch máy, mất dấu tiếng Việt. Rubric thêm: văn bản không dấu coi là FAIL. |

Mẫu hình của tone_ok: trong 10 bất đồng, 6 là judge bỏ sót (fn) vì chỉ nhìn từ khóa lịch sự ("Dạ", xin lỗi); 4 là judge phạt quá tay vì quy tắc chưa được viết ra. Cả hai nhóm đều sửa được bằng rubric cụ thể hơn.

## Kết luận
- **helpful bị loại.** Precision = 1.0 nhưng recall chỉ 0.3: trong 30 reply người gắn FAIL, judge chỉ bắt được 9 và bỏ sót 21 (fn = 21). 18 ca bỏ sót là reply nêu số tiền khác ledger (ví dụ HL-015 nói 55.000đ, ledger ghi 40.000đ; HL-020 nói 90.000đ, ledger ghi 120.000đ); 3 ca còn lại là câu cụt "Ok bạn, đơn … xử lý rồi nhé" (HL-047, HL-091, HL-097). Judge chỉ đọc reply, không thấy ledger, nên reply lịch sự mà sai số vẫn qua. Precision = 1.0 dễ gây ngộ nhận: judge không báo nhầm, nhưng bỏ lọt 70% lỗi thật. Tỉ lệ FAIL quan sát 0.09 so với 0.30 thật; Rogan-Gladen kéo về 0.30, nhưng phải hiệu chỉnh lớn như vậy chứng tỏ judge không đủ tin cậy làm gate.
- **Lỗi số tiền không giao cho judge.** Reply sai số so với ledger là FM-08, chấm bằng code đọc ledger. Đây là quy tắc "tiền và approval luôn là code".
- **tone_ok dùng được** vì qua cả 3 sàn, nhưng các bất đồng ở trên cho thấy rubric cần các chỉnh sửa đã nêu. Sau khi sửa, cần hiệu chuẩn lại trên nhãn người mới.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (n=100); cần nhãn người mới để có held-out thật. Nhãn người cũng có thể sai (H-081), nên κ là ước lượng chứ không phải chân lý.
