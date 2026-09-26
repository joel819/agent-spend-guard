"""Many agents proposing at once must not overshoot the daily cap (check-and-reserve is atomic)."""
from concurrent.futures import ThreadPoolExecutor

from app.guard import Proposal, build_guard


def test_parallel_proposals_cannot_exceed_daily_cap(sessions, policy, wallet, clock):
    guard = build_guard(sessions=sessions, policy=policy, wallet=wallet, clock=clock)

    def one(i):
        return guard.propose(Proposal(f"agent-{i}", "Acme", "software", "burst", 3000, "EUR")).status

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(one, range(20)))
    assert statuses.count("executed") == 6  # 6 x 30.00 = 180.00; a 7th would be 210.00
    assert statuses.count("rejected") == 14
    assert guard.summary()["used_today_cents"] == 18000
    assert wallet.balance_cents() == 100000 - 18000


def test_two_processes_share_the_lock(sessions, policy, wallet, clock, tmp_path):
    """A second Guard on the same file (like the API and CLI at once) sees the same usage."""
    a = build_guard(sessions=sessions, policy=policy, wallet=wallet, clock=clock)
    b = build_guard(sessions=sessions, policy=policy, wallet=wallet, clock=clock)
    a.propose(Proposal("x", "Acme", "software", "one", 5000, "EUR"))
    a.propose(Proposal("x", "Acme", "software", "one", 5000, "EUR"))
    a.propose(Proposal("x", "Acme", "software", "one", 5000, "EUR"))
    assert b.propose(Proposal("y", "Acme", "software", "two", 5001, "EUR")).status == "rejected"
