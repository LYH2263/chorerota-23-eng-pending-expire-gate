"""造数辅助：只走 HTTP API，不 import 任何 db/sqlite，不直连数据库造结果。

所有写操作都经过后端接口：生成周表、申请对调、标记过期、确认对调。
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:10100")


class ApiError(Exception):
    def __init__(self, status: int, detail: str, method: str, path: str):
        super().__init__(f"{method} {path} -> {status}: {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode())
                detail = payload.get("detail", json.dumps(payload, ensure_ascii=False))
            except Exception:
                detail = e.reason
            raise ApiError(e.code, str(detail), method, path)

    # --- 只读 ---
    def health(self):
        return self._call("GET", "/api/health")

    def list_weeks(self):
        return self._call("GET", "/api/weeks")

    def board(self, week_id: int):
        return self._call("GET", f"/api/weeks/{week_id}/board")

    def list_swaps(self):
        return self._call("GET", "/api/swaps")

    def get_swap(self, swap_id: int):
        for row in self.list_swaps():
            if row["id"] == swap_id:
                return row
        return None

    # --- 写操作（全部经 API） ---
    def generate_week(self, week_id: int, days: int = 7):
        return self._call("POST", f"/api/weeks/{week_id}/generate", {"days": days})

    def request_swap(self, week_id: int, a_day: int, a_task: int, b_day: int, b_task: int,
                     note: str = ""):
        return self._call("POST", f"/api/weeks/{week_id}/swaps", {
            "a_day": a_day, "a_task": a_task, "b_day": b_day, "b_task": b_task, "note": note,
        })

    def expire_swap(self, swap_id: int):
        return self._call("POST", f"/api/swaps/{swap_id}/expire", {})

    def confirm_swap(self, swap_id: int):
        return self._call("POST", f"/api/swaps/{swap_id}/confirm", {})


def grid_snapshot(board: dict) -> dict:
    """看板 -> {(day, task_id): member_id}，用于断言周格是否变动。"""
    return {(a["day"], a["task_id"]): a["member_id"] for a in board["assignments"]}


def pick_two_disjoint_pairs(board: dict):
    """从看板里挑两笔合法对调：同日内两个不同负责人的格子，且两笔不共用格子。"""
    by_day = {}
    for a in board["assignments"]:
        by_day.setdefault(a["day"], []).append(a)
    pairs = []
    used = set()
    for day in sorted(by_day):
        slots = sorted(by_day[day], key=lambda s: s["task_id"])
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                s1, s2 = slots[i], slots[j]
                cells = {(s1["day"], s1["task_id"]), (s2["day"], s2["task_id"])}
                if s1["member_id"] != s2["member_id"] and not (cells & used):
                    pairs.append((
                        (s1["day"], s1["task_id"]),
                        (s2["day"], s2["task_id"]),
                    ))
                    used |= cells
                    break
            if len(pairs) == 2:
                return pairs
    raise RuntimeError(f"看板里挑不出两笔互不共用格子的合法对调: {pairs=}")


def make_two_pending(client: ApiClient, week_id: int = 1):
    """经 API 生成一周并造两笔 pending，返回快照与两笔单号（先 expire 第一笔由调用方决定）。"""
    client.generate_week(week_id, days=7)
    board_before = client.board(week_id)
    (a0, a1), (b0, b1) = pick_two_disjoint_pairs(board_before)
    swap_a = client.request_swap(
        week_id, a0[0], a0[1], a1[0], a1[1], note="e2e-expiry-candidate")["id"]
    swap_b = client.request_swap(
        week_id, b0[0], b0[1], b1[0], b1[1], note="e2e-fresh-candidate")["id"]
    return {
        "week_id": week_id,
        "grid_origin": grid_snapshot(board_before),
        "pair_a": (a0, a1),
        "pair_b": (b0, b1),
        "swap_a": swap_a,
        "swap_b": swap_b,
    }
