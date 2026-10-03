#!/usr/bin/env python3
"""入口脚本：过期对调确认门禁（端到端，纯 API）。

流程：经 API 生成一周并造两笔 pending → 一笔标过期 →
确认过期单须失败且周格原样 → 确认未过期单成功并换格 →
列表状态与看板格位一致 → 重复确认须失败（幂等）。

过期口径：库内 status 标记（stored flag）为准，确认时不另查时钟；
前端 Swaps 页同一口径（仅 status==='pending' 可确认）。

用法：
  python3 scripts/expire_gate/run.py                 # 自起临时后端（独立 DATA_DIR）
  python3 scripts/expire_gate/run.py --base-url http://127.0.0.1:10100  # 打已有服务
任一断言失败 → 退出码非零。
"""
import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory import (Api, ApiError, board_map, confirm_swap, create_swap,  # noqa: E402
                     expire_swap, generate_week, get_swap)
from report import Report  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
WEEK_ID = 1
DAYS = 7


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_health(base: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def pick_pair(board: dict, used: set) -> tuple:
    """从看板格位中挑两个成员不同、且未占用的格（对调合法性的最小条件）。"""
    keys = [k for k in sorted(board) if k not in used]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if board[keys[i]] != board[keys[j]]:
                return keys[i], keys[j]
    raise RuntimeError("看板上找不到两格成员不同的合法对调组合")


def run_checks(api: Api, rep: Report):
    # 阶段 1：经 API 生成一周
    rep.stage("1 生成周表")
    tasks = api.call("GET", "/api/tasks")
    n_clean = sum(1 for t in tasks if t["data_quality"] == "clean" and t["weight"] > 0)
    gen = generate_week(api, WEEK_ID, DAYS)
    rep.check("generate 返回格数 = 天数×干净任务数",
              gen["count"] == DAYS * n_clean, f"count={gen['count']} 期望={DAYS * n_clean}")
    board0 = board_map(api, WEEK_ID)
    rep.check("看板格位数与生成一致", len(board0) == gen["count"], f"board={len(board0)}")

    # 阶段 2：造两笔 pending
    rep.stage("2 造两笔 pending 对调")
    a1, b1 = pick_pair(board0, set())
    a2, b2 = pick_pair(board0, {a1, b1})
    sw1 = create_swap(api, WEEK_ID, *a1, *b1, note="gate-expire")
    sw2 = create_swap(api, WEEK_ID, *a2, *b2, note="gate-confirm")
    rep.check("两笔均为 pending",
              sw1["status"] == "pending" and sw2["status"] == "pending",
              f"#{sw1['id']}={sw1['status']} #{sw2['id']}={sw2['status']}")
    rep.check("列表可查且为 pending",
              (get_swap(api, sw1["id"]) or {}).get("status") == "pending"
              and (get_swap(api, sw2["id"]) or {}).get("status") == "pending")

    # 阶段 3：将其中一笔标为过期
    rep.stage("3 标记过期")
    exp = expire_swap(api, sw1["id"])
    rep.check("expire 返回 expired", exp.get("status") == "expired")
    e = api.expect_error("POST", f"/api/swaps/{sw1['id']}/expire", {})
    rep.check("重复标记被拒", e.status == 400 and e.detail == "not_pending",
              f"HTTP {e.status} {e.detail}")

    # 阶段 4：确认过期单必须失败且周格保持原样
    rep.stage("4 过期单确认被拒")
    pre = board_map(api, WEEK_ID)
    e = api.expect_error("POST", f"/api/swaps/{sw1['id']}/confirm", {})
    rep.check("确认过期单返回 400/swap_expired",
              e.status == 400 and e.detail == "swap_expired", f"HTTP {e.status} {e.detail}")
    rep.check("周格保持原样", board_map(api, WEEK_ID) == pre, "board 快照逐格比对")

    # 阶段 5：确认未过期单成功并换格
    rep.stage("5 未过期单确认换格")
    ok = confirm_swap(api, sw2["id"])
    rep.check("确认成功", ok.get("ok") is True)
    after = board_map(api, WEEK_ID)
    rep.check("A 格换成原 B 成员", after[(a2[0], a2[1])] == board0[(b2[0], b2[1])],
              f"{a2}: {board0[(a2[0], a2[1])]}→{after[(a2[0], a2[1])]}")
    rep.check("B 格换成原 A 成员", after[(b2[0], b2[1])] == board0[(a2[0], a2[1])],
              f"{b2}: {board0[(b2[0], b2[1])]}→{after[(b2[0], b2[1])]}")
    rep.check("过期单涉及格位未被波及",
              after[(a1[0], a1[1])] == board0[(a1[0], a1[1])]
              and after[(b1[0], b1[1])] == board0[(b1[0], b1[1])])

    # 阶段 6：列表状态与看板格位一致
    rep.stage("6 列表↔看板一致")
    s1, s2 = get_swap(api, sw1["id"]), get_swap(api, sw2["id"])
    rep.check("过期单状态=expired 且其格位保持原始成员",
              s1 and s1["status"] == "expired"
              and after[(s1["a_day"], s1["a_task"])] == board0[(s1["a_day"], s1["a_task"])]
              and after[(s1["b_day"], s1["b_task"])] == board0[(s1["b_day"], s1["b_task"])],
              f"status={s1 and s1['status']}")
    rep.check("成交单状态=confirmed 且看板已换格",
              s2 and s2["status"] == "confirmed"
              and after[(s2["a_day"], s2["a_task"])] == board0[(s2["b_day"], s2["b_task"])]
              and after[(s2["b_day"], s2["b_task"])] == board0[(s2["a_day"], s2["a_task"])],
              f"status={s2 and s2['status']}")

    # 阶段 7：幂等——已成交/已过期的单再确认均须失败
    rep.stage("7 幂等")
    e1 = api.expect_error("POST", f"/api/swaps/{sw2['id']}/confirm", {})
    rep.check("已成交单再确认被拒", e1.status == 400 and e1.detail == "not_pending",
              f"HTTP {e1.status} {e1.detail}")
    e2 = api.expect_error("POST", f"/api/swaps/{sw1['id']}/confirm", {})
    rep.check("过期单再确认仍被拒", e2.status == 400 and e2.detail == "swap_expired",
              f"HTTP {e2.status} {e2.detail}")
    rep.check("失败确认未改动看板", board_map(api, WEEK_ID) == after)


def main() -> int:
    ap = argparse.ArgumentParser(description="过期对调确认门禁")
    ap.add_argument("--base-url", help="打已有服务；缺省自起临时后端")
    args = ap.parse_args()

    rep = Report()
    proc, tmp = None, None
    try:
        if args.base_url:
            base = args.base_url.rstrip("/")
        else:
            tmp = tempfile.TemporaryDirectory(prefix="expire-gate-")
            port = free_port()
            env = {**os.environ, "DATA_DIR": tmp.name}
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=BACKEND_DIR, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f"http://127.0.0.1:{port}"

        rep.stage("0 环境")
        up = wait_health(base)
        rep.check("后端健康检查通过", up, base)
        if not up:
            return rep.finish()

        run_checks(Api(base), rep)
        return rep.finish()
    except (ApiError, AssertionError, RuntimeError) as e:
        print(f"\n✗ 门禁执行中断：{e}", file=sys.stderr)
        return rep.finish() or 1
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if tmp:
            tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
