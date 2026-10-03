"""阶段报告：记录各阶段断言，输出报告并给出退出码。

任一断言失败 → finish() 返回非零退出码。
"""


class Report:
    def __init__(self):
        self.stages = []          # [{"name": str, "checks": [(label, ok, detail)]}]
        self._current = None

    def stage(self, name: str):
        self._current = {"name": name, "checks": []}
        self.stages.append(self._current)

    def check(self, label: str, ok: bool, detail: str = ""):
        assert self._current is not None, "check() 前须先 stage()"
        self._current["checks"].append((label, bool(ok), detail))

    @property
    def failures(self):
        return [(s["name"], label, detail)
                for s in self.stages for label, ok, detail in s["checks"] if not ok]

    def finish(self) -> int:
        total = 0
        for s in self.stages:
            bad = sum(1 for _, ok, _ in s["checks"] if not ok)
            mark = "✓" if bad == 0 else "✗"
            print(f"\n[{mark}] 阶段：{s['name']}")
            for label, ok, detail in s["checks"]:
                total += 1
                line = f"    {'✓' if ok else '✗'} {label}"
                if detail:
                    line += f"  —— {detail}"
                print(line)
        fails = self.failures
        print("\n" + "=" * 56)
        if fails:
            print(f"结果：FAIL —— {len(fails)}/{total} 条断言未过，退出码 1")
            for stage, label, detail in fails:
                print(f"  失败于[{stage}] {label} {detail}")
            return 1
        print(f"结果：PASS —— {total} 条断言全部通过，退出码 0")
        return 0
