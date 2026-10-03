# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
python backend/e2e/run_expiry_gate.py   # 过期对调确认门禁 E2E，全程走 API，失败非零退出
```

过期口径：对调单过期以库内 `status=expired` 标记为准（`POST /api/swaps/{id}/expire`），
不看确认时刻时钟；过期单确认返回 `400 expired`，已确认单重复确认返回 `400 already_confirmed`，前后端同一组状态字面值。
E2E 三个源文件：`run_expiry_gate.py`（入口/编排）、`data_factory.py`（纯 HTTP 造数）、`stage_report.py`（阶段报告）。

种子含 clean/dirty。0-1 空桩：`streak_badge` / `skip_week` / `chore_photo`。
