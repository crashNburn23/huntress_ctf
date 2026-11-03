"""Toy lane solver used by the tests and the offline rehearsal against tests/mock_gm.py.

It shows the shape of a real lane solver: read members, answer what it understands, leave the rest blank. The
mock asks for the sum, count and max of the numbers in numbers.txt; the product question is left blank on
purpose so it escalates to a fixer, who answers it with a plugin.

Use it for every lane in a rehearsal:  RACE_LANE_SOLVER="warm=example,meta=example,..."
"""
import re

from . import Lane


class ExampleLane(Lane):
    def solve(self, questions, members):
        out = {}
        for q in questions:
            raw = members.for_qid(q["id"]).get("numbers.txt")
            if raw is None:
                continue
            nums = [int(x) for x in raw.split()]
            m = re.search(r"what is the (sum|count|max) of", q.get("question", ""))
            if m and nums:
                out[q["id"]] = str({"sum": sum(nums), "count": len(nums), "max": max(nums)}[m.group(1)])
        return out


LANE_CLASS = ExampleLane
