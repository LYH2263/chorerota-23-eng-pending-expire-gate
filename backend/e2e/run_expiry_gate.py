#!/usr/bin/env python3
"""入口：工程化过期对调确认门禁 E2E。

流程（全部经 HTTP API，禁止绕过 API 直改库）：
  1. 经 API 生成一周并造两笔 pending；
  2. 将其中一笔标记过期；
  3. 断言确认过期单必须失败、周格保持原样；
  4. 断言确认未过期单成功并换格；
  5. 断言列表中过期单状态与看板格位一致；
  6. 未过期单再确认一次必须失败（幂等），看板不再变化。

任一断言失败 -> 非零退出。默认自行拉起 uvicorn（临时 DATA_DIR），
设 E2E_BASE_URL 可指向外部已运行的服务。

用法：
  python backend/e2e/run_expiry_gate.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BACKEND_DIR))

from data_factory import ApiClient, ApiError, grid_snapshot, make_two_pending  # noqa: E402
from stage_report import StageReport  # noqa: E402

WEEK_ID = 1
EXPIRED_CODE = "expired"
ALREADY_CONFIRMED_CODE = "already_confirmed"


def wait_healthy(client: ApiClient, proc: subprocess.Popen, timeout: float = 20.0):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"uvicorn 提前退出 (code={proc.returncode})\n{err}")
        try:
            if client.health().get("ok"):
                return
        except Exception as e:  # 服务尚未起来
            last_err = e
        time.sleep(0.25)
    raise RuntimeError(f"服务健康检查超时: {last_err}")


def spawn_server():
    port = os.environ.get("E2E_PORT", "10100")
    data_dir = tempfile.mkdtemp(prefix="chorerota-e2e-")
    env = dict(os.environ)
    env["DATA_DIR"] = data_dir
    env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", port],
        cwd=BACKEND_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return proc, f"http://127.0.0.1:{port}", data_dir


def expect_api_error(report, stage, fn, expected_status: int, expected_detail: str):
    """断言一次 API 调用必须以指定 HTTP 状态码和 detail 失败。"""
    try:
        fn()
    except ApiError as e:
        ok = e.status == expected_status and e.detail == expected_detail
        report.check(stage, ok,
                     f"{expected_status}/{expected_detail}",
                     f"期望 {expected_status}/{expected_detail}，实得 {e.status}/{e.detail}")
        return True
    except Exception as e:
        report.check(stage, False, "", f"预期 API 失败，却抛出 {type(e).__name__}: {e}")
        return False
    else:
        report.check(stage, False, "", f"预期 {expected_status}/{expected_detail}，调用却成功")
        return False


def run() -> int:
    report = StageReport()
    proc = None
    external = bool(os.environ.get("E2E_BASE_URL"))
    try:
        if external:
            base_url = os.environ["E2E_BASE_URL"]
            report.info("服务模式", f"外部服务 {base_url}（不自行拉起）")
        else:
            proc, base_url, data_dir = spawn_server()
            report.info("服务模式", f"内置 uvicorn {base_url}，临时 DATA_DIR={data_dir}")
        client = ApiClient(base_url)
        if proc is not None:
            wait_healthy(client, proc)
        report.check("阶段0 健康检查", client.health().get("ok") is True, "/api/health ok")

        # 阶段1：经 API 生成一周并造两笔 pending（造数辅助，不碰数据库）
        ctx = make_two_pending(client, WEEK_ID)
        swap_x, swap_fresh = ctx["swap_a"], ctx["swap_b"]
        origin = ctx["grid_origin"]
        px, py = ctx["pair_a"]
        fx, fy = ctx["pair_b"]
        report.info("阶段1 造数",
                    f"周={WEEK_ID} 格数={len(origin)} 待过期单=#{swap_x} {px}<->{py}，"
                    f"未过期单=#{swap_fresh} {fx}<->{fy}")
        sx = client.get_swap(swap_x)
        sf = client.get_swap(swap_fresh)
        report.check("阶段1 两笔均 pending",
                     sx["status"] == "pending" and sf["status"] == "pending",
                     f"#{swap_x}=pending #{swap_fresh}=pending",
                     f"#{swap_x}={sx['status']} #{swap_fresh}={sf['status']}")

        # 阶段2：将其中一笔经 API 标记为过期
        r = client.expire_swap(swap_x)
        report.check("阶段2 标记过期成功",
                     r.get("status") == "expired" and client.get_swap(swap_x)["status"] == "expired",
                     f"#{swap_x} 库内状态=expired")

        # 阶段3：确认过期单必须失败
        expect_api_error(report, "阶段3 过期单确认必须失败",
                         lambda: client.confirm_swap(swap_x), 400, EXPIRED_CODE)

        # 阶段4：过期单确认失败后，周格必须保持原样（整表快照比对）
        after_expired = grid_snapshot(client.board(WEEK_ID))
        report.check("阶段4 周格保持原样",
                     after_expired == origin,
                     f"{len(origin)} 个格位全部未变",
                     f"发生变化的格位: "
                     f"{[k for k in origin if after_expired.get(k) != origin[k]]}")

        # 阶段5：确认未过期单成功，且恰好只换目标两格
        cr = client.confirm_swap(swap_fresh)
        after_fresh = grid_snapshot(client.board(WEEK_ID))
        swapped_cells_ok = (
            after_fresh[fx] == origin[fy] and after_fresh[fy] == origin[fx]
        )
        untouched = {k: v for k, v in origin.items() if k not in (fx, fy)}
        others_ok = all(after_fresh.get(k) == v for k, v in untouched.items())
        report.check("阶段5a 未过期单确认成功", cr.get("ok") is True, f"#{swap_fresh} confirmed")
        report.check("阶段5b 两格换人", swapped_cells_ok,
                     f"{fx}:{origin[fx]}->{after_fresh.get(fx)}，{fy}:{origin[fy]}->{after_fresh.get(fy)}")
        report.check("阶段5c 其余格位不动", others_ok, f"其余 {len(untouched)} 个格位不变")

        # 阶段6：列表状态与看板格位一致
        sx = client.get_swap(swap_x)
        sf = client.get_swap(swap_fresh)
        expired_list_ok = sx["status"] == "expired"
        expired_cells_ok = after_fresh[px] == origin[px] and after_fresh[py] == origin[py]
        confirmed_list_ok = sf["status"] == "confirmed"
        confirmed_cells_ok = after_fresh[fx] == origin[fy] and after_fresh[fy] == origin[fx]
        report.check("阶段6a 列表过期单=expired", expired_list_ok, f"#{swap_x} status={sx['status']}")
        report.check("阶段6b 过期单对应格位未换", expired_cells_ok,
                     f"{px}/{py} 仍是原负责人")
        report.check("阶段6c 列表未过期单=confirmed", confirmed_list_ok, f"#{swap_fresh} status={sf['status']}")
        report.check("阶段6d 已确认单格位已换", confirmed_cells_ok,
                     f"{fx}/{fy} 已互换")

        # 阶段7：未过期单再确认一次必须失败（幂等），看板不得再变
        expect_api_error(report, "阶段7 重复确认必须失败（幂等）",
                         lambda: client.confirm_swap(swap_fresh), 400, ALREADY_CONFIRMED_CODE)
        final_grid = grid_snapshot(client.board(WEEK_ID))
        report.check("阶段7b 重复确认后看板不再变化", final_grid == after_fresh,
                     "格位快照一致")

    except Exception as e:
        report.check("运行异常", False, "", f"{type(e).__name__}: {e}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    failed = report.failures
    print()
    print(report.summary())
    if failed:
        print("失败阶段：" + "；".join(stage for _, stage, _ in failed))
        return 1
    print("全部阶段通过：过期单被门禁拦截，未过期单正常换格，重复确认幂等拒绝。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
