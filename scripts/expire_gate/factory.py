"""造数辅助：过期对调确认门禁的 API 数据构造层。

铁律：一切结果只经 HTTP API 产生，禁止绕过 API 直连数据库改数。
"""
import json
import urllib.error
import urllib.request


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class Api:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                detail = json.loads(raw).get("detail", raw)
            except json.JSONDecodeError:
                detail = raw
            raise ApiError(e.code, detail) from None

    def expect_error(self, method: str, path: str, body: dict | None = None) -> ApiError:
        """调用必须失败；返回错误对象，若意外成功则抛 AssertionError。"""
        try:
            self.call(method, path, body)
        except ApiError as e:
            return e
        raise AssertionError(f"{method} {path} 意外成功（预期失败）")


def generate_week(api: Api, week_id: int = 1, days: int = 7) -> dict:
    return api.call("POST", f"/api/weeks/{week_id}/generate", {"days": days})


def create_swap(api: Api, week_id: int, a_day: int, a_task: int,
                b_day: int, b_task: int, note: str = "") -> dict:
    return api.call("POST", f"/api/weeks/{week_id}/swaps", {
        "a_day": a_day, "a_task": a_task, "b_day": b_day, "b_task": b_task, "note": note,
    })


def expire_swap(api: Api, swap_id: int) -> dict:
    return api.call("POST", f"/api/swaps/{swap_id}/expire", {})


def confirm_swap(api: Api, swap_id: int) -> dict:
    return api.call("POST", f"/api/swaps/{swap_id}/confirm", {})


def board_map(api: Api, week_id: int = 1) -> dict:
    """看板格位快照：{(day, task_id): member_id}"""
    b = api.call("GET", f"/api/weeks/{week_id}/board")
    return {(a["day"], a["task_id"]): a["member_id"] for a in b["assignments"]}


def get_swap(api: Api, swap_id: int) -> dict | None:
    for s in api.call("GET", "/api/swaps"):
        if s["id"] == swap_id:
            return s
    return None
