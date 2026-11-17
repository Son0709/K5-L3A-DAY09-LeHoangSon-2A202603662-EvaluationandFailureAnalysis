# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
python -m pytest -q -m student -o addopts= tests/test_lab9_trace_case.py
```

Lệnh in ra ba phần: các event trong trace, ledger so với nhãn, và lý do của grader Lab 8.

## Case: C-002@11, ticket nói trễ 5 ngày nhưng DB ghi 2 ngày

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (run `R-seeded_regression-C-002-s11`), item E-002 trong báo cáo `E-seeded_regression-20261117-5613`. Cùng lỗi xuất hiện ở baseline: `swarm C-002@55` (`R-swarm-C-002-s55`, trial duy nhất fail trong 70 trial). |
| Triệu chứng | Grader Lab 8 fail: `status resolved != denied`. Ledger ghi hoàn 20.000đ (1 dòng) trong khi nhãn là 0đ, `denied`. Reply "Dạ, LogiX đã hoàn 20.000đ" khớp ledger, nên `reply_amount_matches_ledger` (FM-08) pass: reply trơn tru, lỗi nằm ở thượng nguồn. |
| Bước sai đầu tiên | Event #3 `model_override {"delay_days": 5}`. |
| Vì sao là bước *đầu tiên* | Event #1 `handoff` chỉ giao tool và task. Event #2 `investigator` trả `lookup_order` hợp lệ với `delay_days: 2` (DB là nguồn sự thật). Event #3 ghi đè 2 bằng 5 lấy từ ticket ("trễ 5 ngày"). Các event sau chỉ là hệ quả: #4 `quote` 20.000đ theo `SHIP-LATE-03` (ngưỡng ≥3 ngày), #5 `refund_history` rỗng, #6 `reply` nói đã hoàn 20.000đ. Với `delay_days=2` thì quote là 0đ (`no_entitlement`). |
| Failure mode | **FM-03** ticket_trust (xem `docs/failure_taxonomy.md`). |
| Đối chứng | `fixed C-002@11`: trace chỉ có 4 event, không có `model_override`; event #3 `quote` 0đ (`no_entitlement`), reply "chưa đủ điều kiện hoàn"; ledger 0đ, status `denied`, grader Lab 8 PASS. |
| Regression test | `tests/test_lab9_trace_case.py` (chạy trong job `eval-gate`). `test_seeded_regression_overrides_the_db_with_the_ticket` khẳng định trên shape lỗi: DB `delay_days == 2`, override `5` ở event #3, `DbFactKept` False, `RefundAmountCorrect` False, ledger 20.000đ so với nhãn 0đ. `test_fixed_shape_keeps_the_db_fact_on_the_same_claim` khẳng định trên `fixed`: không có override, mọi grader pass. Test thứ ba kiểm lỗi có sẵn của swarm: fail ở seed 55, đúng ở seed 11. Đã thấy test fail-signal trên shape lỗi và pass trên `fixed` (15/15 test xanh). |
| Chưa chắc chắn | Trace chỉ cho thấy `delay_days` bị ghi đè bằng số trong ticket, không cho thấy *vì sao* swarm chỉ làm vậy ở seed chia hết cho 5 (đó là cách MockLLM chọn lỗi theo seed, không phải hành vi của model thật). Chưa có dữ liệu về việc model thật có tin ticket hơn DB không, hay mức độ. `seeded_regression` bật cả `ticket_trust`, `pre_deducted` và `ignore_denied`; ở C-002 chỉ `ticket_trust` có tác dụng (tôi đã chạy công tắc này một mình và C-002 fail 5/5 seed), nên quy cho FM-03 là hợp lý nhưng dựa trên phép thử tách biệt chứ không chỉ trace này. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
