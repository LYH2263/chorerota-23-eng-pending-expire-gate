"""阶段报告：每个断言阶段打印一行结果；任意断言失败由入口脚本非零退出。"""
import sys

PASS = "PASS"
FAIL = "FAIL"
INFO = "INFO"

_GREEN = "\033[32m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


class StageReport:
    def __init__(self, stream=sys.stdout, color: bool = True):
        self.stream = stream
        self.color = color
        self.records = []

    def _line(self, tag: str, stage: str, detail: str = ""):
        label = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "INFO": "ℹ️  INFO"}.get(tag, tag)
        if self.color and getattr(self.stream, "isatty", lambda: False)():
            paint = {PASS: _GREEN, FAIL: _RED, INFO: _CYAN}.get(tag, "")
            label = f"{paint}{label}{_RESET}" if paint else label
        text = f"[{label}] {stage}" + (f" — {detail}" if detail else "")
        print(text, file=self.stream)
        self.stream.flush()
        self.records.append((tag, stage, detail))

    def info(self, stage: str, detail: str = ""):
        self._line(INFO, stage, detail)

    def check(self, stage: str, condition: bool, detail: str = "", fail_detail: str = ""):
        """记录一条断言；不抛异常，只记账，由入口脚本最终按 failures 决定退出码。"""
        if condition:
            self._line(PASS, stage, detail)
        else:
            self._line(FAIL, stage, fail_detail or detail)
        return condition

    @property
    def failures(self):
        return [r for r in self.records if r[0] == FAIL]

    def summary(self) -> str:
        total = sum(1 for r in self.records if r[0] in (PASS, FAIL))
        passed = sum(1 for r in self.records if r[0] == PASS)
        return f"{passed}/{total} 阶段通过，{len(self.failures)} 个失败"
