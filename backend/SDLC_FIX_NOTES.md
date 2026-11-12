# Ghi chú sửa luồng dev, test và preview

## Phạm vi

Giữ kiến trúc BA → SRS → Design → Dev/Testing → DevOps, các runner, API và bảng DB hiện có. Không thêm agent, queue, framework điều phối hay migration DB. Hỗ trợ test cho service Python, Node.js/TypeScript và frontend HTML/JS tĩnh; mỗi service dùng runner riêng.

## Chẩn đoán từ dự án thực tế

Sandbox `da2ab3bb-b5c7-4bba-986e-1ae17c380dbd`:

1. DB ghi system test `PASSED` với **3 passed / 15 skipped**. File test bắt lỗi import rồi gọi `pytest.skip`, runner cũ chỉ kiểm tra exit code 0.
2. Chạy image thật xác nhận `ModuleNotFoundError: No module named 'app.repositories'`. Các service nhập repository chưa được sinh; một số unit test dùng mock nên không phát hiện.
3. Log container `portfolio_backend` xác nhận lỗi pydantic-settings đọc `CORS_ORIGINS`: Compose truyền chuỗi phân cách dấu phẩy nhưng trường cấu hình yêu cầu JSON array.
4. Compose dùng PostgreSQL nhưng requirements chưa khai báo driver tương ứng; healthcheck Dockerfile trỏ `/api/health` trong khi ứng dụng khai báo `/health`.
5. Frontend đã có nhưng backend root trả JSON và chưa phục vụ frontend. Có container chạy không đồng nghĩa người dùng xem được website.
6. Prompt test/system test cũ ép Python/FastAPI; context bị cắt ở 2.000–8.000 ký tự, thiếu interface và file quan trọng. System test được sinh lại sau mỗi lượt sửa nên có thể thay đổi/né lỗi thay vì kiểm chứng bản sửa.
7. API Preview và feedback vẫn dùng code riêng, cố định `web:80`, không kiểm tra UI; một số đường gọi `down -v` làm mất dữ liệu.

## Hướng xử lý và luồng vận hành

1. BA chốt yêu cầu; SRS/Design lưu DB và xuất `SRS.json`, `design.json` vào sandbox. Design chỉ rõ stack, service root, entrypoint, preview service/path/container port và interface giữa module.
2. Kiểm tra DAG: ID phải duy nhất, dependency phải tồn tại, không có vòng lặp. Chạy module theo dependency.
3. Dev đọc cây file và toàn bộ nội dung các file được chọn trong giới hạn context. Nội dung file không bị cắt giữa JSON. Các dependency đã sinh nhưng chưa pass cũng có trong context để giữ đúng interface.
4. Hợp nhất file và manifest thay vì xóa file/thư viện/script của module khác. Kiểm tra cú pháp/import Python nội bộ trước khi mock unit test có thể che lỗi. Lỗi sinh code, lỗi sinh test và lỗi chạy test được ghi nhận với số lượt thử hữu hạn.
5. Testing Agent sở hữu test; bỏ qua test do Dev trả kèm trong legacy design, không cho Dev sửa bộ test đã chốt. Runner nhận diện DOM để chọn jsdom. Với Vitest, giữ plugin/alias/setup của dự án nhưng dùng cấu hình trong bản sao để bảo đảm test target trong `tests/` không bị `include: src/**` loại bỏ; giới hạn worker để tránh lỗi tài nguyên. Nhận diện runner theo service và mã nguồn: Python → pytest; JS/TS → Vitest, hoặc Jest/node:test nếu manifest khai báo. Một `package.json` frontend không chuyển backend Python sang Node.
6. Test chạy trong Docker với source mount **read-only**, chép sang `/work`; cài dependency và build ở bản sao. Test DB mặc định là SQLite trong `/tmp`, không ghi DB test vào source. Log/report nằm trong `.sdlc/reports/<run-id>/`.
7. Đọc JUnit XML/Jest JSON. Không có report hợp lệ, không có test pass, setup/collection error hoặc exit code lỗi đều không đạt. System test còn skip cũng không đạt — kể cả exit code 0.
8. Sinh và kiểm tra system suite một lần, lưu theo `id_version`. Các lượt sửa dùng lại suite này. Chạy system riêng một process để tránh mock từ unit test làm sai lệch import; sau đó chạy cả thư mục tests để bắt regression. Frontend có build script thì build phải đạt trước test. Agent sửa mã ứng dụng và chạy lại tối đa 3 lượt system test.
9. DevOps đọc source thực tế để đóng gói. Preview kiểm tra Compose config, dùng project name riêng, bỏ fixed container_name, chỉ publish service web lên loopback, giữ volume. Dùng `docker compose up --wait`, đọc service/port thực từ JSON và thu log khi lỗi.
10. Preview phải trả HTTP 2xx; nếu có frontend thì phải là HTML, không chấp nhận root JSON/404/500. Kiểm tra script/CSS cùng origin không lỗi hoặc trả HTML fallback. Có tối đa 3 lượt khởi chạy/sửa theo log. Bản sửa preview làm đổi code/dependency thì chạy lại system + regression.
11. `PREVIEW` chỉ được đặt khi preview thực sự đạt kiểm tra. Preview có thể được cung cấp để phản hồi khi test còn lỗi, nhưng báo rõ `CẦN TIẾP TỤC SỬA`, `system_test_passed=false` và module chưa đạt. Không đồng nhất có preview với đã nghiệm thu.
12. Feedback dùng source thực tế, system suite hiện có và cùng cơ chế preview; có vòng sửa giới hạn cho cả system test và startup. Nút Preview/API cũng dùng runner kiểm tra chung, không giả định service `web` hay port 80.

## Các file đã sửa/thêm

| File | Phần thay đổi |
|---|---|
| `app/agents/design_agent.py` | Bỏ giả định Python; bổ sung execution contract, DAG, interface và bootstrap/frontend integration. |
| `app/agents/dev_agent.py` | Sinh/sửa theo stack và source thật; dependency/schema/settings/DB driver/serve frontend; không sửa test để né lỗi. |
| `app/agents/testing_agent.py` | pytest/Vitest/Jest/node theo plan; test fixture/schema/DI thực tế; cấm skip lỗi import, route đoán, pass giả trong system test. |
| `app/agents/devops_agent.py` | Đóng gói theo source, đúng kiểu env/driver/health route, frontend/API proxy, không fixed container_name hay publish DB; README đúng stack. |
| `app/agents/module_runner.py` | Chọn runner từng service, kiểm tra local import, validate output test, retry có persist, source read-only, report có cấu trúc, timeout/cleanup container riêng. |
| `app/agents/pipeline_runner.py` | Lưu đặc tả, xử lý lỗi pipeline, cố định system suite, regression, sửa startup dựa log, preview HTML/asset/service/port thực, tách chất lượng test khỏi khả năng xem preview. |
| `app/agents/orchestrator.py` | Dùng JSON parser chung, feedback đọc source thật và sửa/test/preview có retry; hướng dẫn bàn giao đúng stack. |
| `app/services/file_service.py` | Kiểm tra path trước ghi, giữ dotfile/code, hợp nhất dependency manifest, snapshot/context đầy đủ file được chọn, loại dependency/build/cache/DB khỏi context. |
| `app/services/module_service.py` | Context source thực tế, đọc JUnit/Jest, tính lỗi/setup/skip, quality gate, DAG validation và lấy version theo project. |
| `app/services/json_utils.py` | Parse JSON trước khi sửa; không dùng regex làm thay đổi chuỗi source hợp lệ; từ chối JSON bị cắt; merge file theo path. |
| `app/services/gemini_service.py` | Báo lỗi provider/output rỗng/output bị cắt; không trả `{}` giả kết quả thành công. |
| `main.py` | API Preview gọi chung runner, trả URL thật và chỉ cập nhật trạng thái theo kết quả kiểm tra. |
| `requirements.txt` | Bổ sung dependency đang dùng nhưng chưa khai báo cho API client/auth và kiểm thử backend. |
| `tests/test_pipeline_resilience.py` | Kiểm thử hồi quy cho multi-runtime, missing import, skip giả pass, retry, frozen suite, manifest/file preservation, DAG và preview. |
| `tests/verify_docker_runtimes.py` | Script Docker thật: FastAPI + SQLAlchemy schema/CRUD, Express API, HTML tĩnh, build/system/regression và Compose HTML/CSS; fixture/container riêng được dọn sau chạy. |
| `tests/verify_llm_pipeline.py` | Script chạy LLM thật từ SRS tới preview, dùng DB in-memory, giữ sandbox/result/preview mẫu riêng; sử dụng API provider đang cấu hình. |
| `SDLC_FIX_NOTES.md` | Tài liệu này. |

## Cách chạy sau sửa

Từ thư mục gốc dự án, cài dependency rồi **khởi động lại backend** bằng cách bạn đang dùng. Bản sửa không thay đổi frontend của hệ thống hoặc schema DB.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHONPATH = "backend"
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe backend/tests/verify_docker_runtimes.py
```

Có thể chạy thêm E2E qua provider thực (có sử dụng quota API và giữ sandbox/preview mẫu):

```powershell
.\.venv\Scripts\python.exe backend/tests/verify_llm_pipeline.py
```

Lệnh Docker cần Docker Desktop chạy và kết nối tải image/thư viện nếu cache chưa có. Không chạy script kiểm chứng song song với chính nó do tên Compose của fixture cố định.

Tạo project mới để kiểm tra trọn luồng với execution contract mới. Với project cũ đang `CODING_FAILED`/`PREVIEW`, gửi feedback mô tả lỗi để agent đọc source, sửa và test lại. Chỉ bấm Preview sẽ kiểm tra/khởi chạy cấu hình hiện có; nút này không tự sinh lại source thiếu.

`design.json` có thể khai báo:

```json
{"execution":{"preview_service":"frontend","preview_path":"/","container_port":3000}}
```

Tên service và port phải khớp Compose thực tế. Nếu không khai báo, runner chọn service web đang publish port theo thứ tự frontend/web/client/ui/app/backend/api, sau đó xác nhận HTTP và HTML.

## Kết quả kiểm chứng và giới hạn

- **33 kiểm thử hồi quy backend đạt**, chạy độc lập với LLM/DB thật.
- **2 kiểm thử tích hợp Docker đạt**: nhóm runtime kiểm tra FastAPI + SQLAlchemy (tạo schema, tạo/đọc dữ liệu và lỗi đầu vào), Express API, HTML tĩnh; nhóm preview kiểm tra Compose và HTTP/HTML/CSS. Vitest fixture cố tình chỉ include `src/**` để xác nhận runner vẫn chạy test trong `tests/`.
- Chạy lại chính system suite lỗi của sandbox cũ: **3 passed, 15 skipped → FAILED**, kèm lý do thiếu `app.repositories`. Chỉ thêm report dưới `.sdlc`; chưa chỉnh source ứng dụng đã sinh trong sandbox này. Lượt kiểm chứng LLM đầu tiên cũng phát hiện design giao test cho Dev, Vitest discovery không khớp và báo cáo rỗng; các lỗi này đã được sửa rồi kiểm chứng lại bằng lượt LLM thành công nêu dưới.
- Không tuyên bố sandbox portfolio cũ đã được chữa hết hoặc có link preview sử dụng được. Nó còn cần sửa source/config đã chẩn đoán, thông qua feedback hoặc chạy lại project với luồng mới.
- Đã chạy **LLM thật: SRS → Design → Dev → Unit → System/regression → DevOps → Preview** cho website tip calculator mẫu. Sandbox `sdlc-e2e-821901d26a57`: **3/3 module PASSED ở lần đầu, 25 unit test PASSED, system + regression 32 PASSED, 0 skipped**, `quality_passed=true`. Preview mẫu: **http://localhost:49530/**. Kết quả chi tiết: `sandbox/sdlc-e2e-821901d26a57/.sdlc/e2e-result.json`. DB kiểm chứng là in-memory nên project mẫu không xuất hiện trong danh sách project của UI. Đây là kiểm chứng một website nhỏ, không phải bằng chứng mọi nghiệp vụ/framework đều đạt.
- System test hiện là integration + unit regression; preview là HTTP/HTML/asset smoke test. Chưa có trình duyệt tự động kiểm tra click, layout, lỗi JavaScript runtime hay toàn bộ nghiệp vụ E2E.
- Môi trường test Python mặc định dùng SQLite tạm. Dự án cần tính năng đặc thù PostgreSQL/MySQL/Mongo/Redis phải có fixture/container test phù hợp; không coi SQLite là kiểm chứng tương đương cho các tính năng đó.
- Test adapter hiện hỗ trợ Python/Node/static; PHP/Java/.NET/Ruby chưa có adapter riêng. Unsupported runtime hoặc test không hợp lệ phải được báo lỗi rõ, không giả pass.
- LLM vẫn có thể sinh sai code/test; cơ chế retry hữu hạn và báo cáo minh bạch không đảm bảo mọi yêu cầu website bất kỳ sẽ tự pass.
- Luồng vẫn chạy trong request hiện có; chưa có durable background job tự resume sau server restart. Không thay đổi phần này để giữ kiến trúc hiện tại.

## Tài liệu công cụ đã đối chiếu

- [Docker Compose JSON trạng thái/port](https://docs.docker.com/reference/cli/docker/compose/ps/)
- [Docker Compose config JSON](https://docs.docker.com/reference/cli/docker/compose/convert/)
- [Vitest JUnit reporter](https://v3.vitest.dev/guide/reporters)
