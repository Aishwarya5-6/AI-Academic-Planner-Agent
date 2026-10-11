"""Demo data so the planner can be explored without typing a syllabus."""
from __future__ import annotations

from datetime import date, timedelta

from planner.agents.syllabus_analyzer import with_revision

SAMPLE = [
    ("Data Structures & Algorithms", 18, 4, [
        ("Arrays, strings & two pointers", 3, 2), ("Linked lists, stacks & queues", 3, 2),
        ("Trees & binary search trees", 4, 3), ("Heaps & priority queues", 3, 3),
        ("Graphs: BFS, DFS, shortest paths", 5, 4), ("Dynamic programming", 6, 5),
    ]),
    ("Linear Algebra", 26, 3, [
        ("Vectors & matrix operations", 2, 2), ("Systems of equations & Gaussian elimination", 3, 3),
        ("Vector spaces & subspaces", 4, 4), ("Determinants", 2, 3),
        ("Eigenvalues & diagonalization", 5, 4), ("Orthogonality & least squares", 4, 4),
    ]),
    ("Operating Systems", 34, 2, [
        ("Processes & threads", 3, 2), ("CPU scheduling", 3, 3), ("Synchronization & deadlocks", 5, 4),
        ("Memory management & paging", 4, 4), ("File systems", 3, 3),
    ]),
]


def load_sample(orch, today: date) -> None:
    db = orch.db
    db.reset()
    pct = db.get_settings()["revision_pct"]
    for name, days, weakness, topics in SAMPLE:
        rows = [{"name": n, "est_hours": h, "difficulty": d} for n, h, d in topics]
        db.add_subject(name, today + timedelta(days=days), weakness, "\n".join(n for n, *_ in topics),
                       with_revision(rows, pct))
    db.log("Planner", f"Loaded demo data: {len(SAMPLE)} subjects.")
    orch.optimizer.replan(today, "demo data loaded")
