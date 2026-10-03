# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
```

种子含 clean/dirty。0-1 空桩：`streak_badge` / `skip_week` / `chore_photo`。

## 过期对调确认门禁

对调单生命周期：`pending → confirmed / expired`。`POST /api/swaps/{id}/expire` 将 pending 单标为过期；确认端点对过期单返回 `400 swap_expired` 且不动周格，对已成交单返回 `400 not_pending`（幂等）。

**过期口径**：取库内 `status` 标记为准，确认时刻不另查时钟——取舍上放弃了时钟判定的自动过期，换来确定性、可审计与可重放；前端 Swaps 页同一口径，仅 `status==='pending'` 渲染确认按钮，不自行推断过期。

```bash
python3 scripts/expire_gate/run.py    # 自起临时后端跑 7 阶段 18 断言；任一失败退出码非零
```

入口 `run.py`、造数辅助 `factory.py`（纯 API，不直连库）、阶段报告 `report.py` 三个源文件分离。
