"""
Regression tests for the four Agent-OS bugs found by showcase_full/:

1. WeightedFairScheduler monopolisation (deficits diverged)
2. IPCManager accepted mail for dead / missing PIDs (dead letters)
3. POST /processes/{pid}/cancel bypassed the kernel (no reclaim, never TERMINATED)
4. POST /processes/{pid}/pause was a no-op between steps (READY processes)
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

import httpx
import pytest
from fastapi import FastAPI

from agent_os.api import routes
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import AgentStepResult, ProcessState, StepStatus
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from sdk.kernel import Kernel


class Idle:
    async def step(self, ctx):
        return AgentStepResult(status=StepStatus.CONTINUE)


@pytest.fixture
async def kernel():
    k = Kernel()
    await k.boot()
    yield k
    await k.shutdown()


@pytest.fixture
async def api(kernel):
    saved = (routes._ks.process_manager, routes._ks.event_manager, routes._ks.metrics_collector,
             routes._ks.ipc_manager, routes._ks.kernel)
    routes.use_kernel(kernel)
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    routes.set_kernel_state(*saved[:4], kernel=saved[4])


# ── 1. Weighted fair scheduling ──────────────────────────────────────────────
def test_weighted_fair_exact_share():
    sched = WeightedFairScheduler()
    procs = [AgentProcess(process_id=i, agent=Idle(), state=ProcessState.READY, weight=w)
             for i, w in ((1, 1), (2, 2), (3, 4))]
    picks = [sched.select_next(procs).process_id for _ in range(70)]
    assert [picks.count(i) for i in (1, 2, 3)] == [10, 20, 40]
    assert set(picks[:7]) == {1, 2, 3}                      # interleaved, nobody waits a full round


def test_weighted_fair_deficits_stay_bounded():
    sched = WeightedFairScheduler()
    procs = [AgentProcess(process_id=i, agent=Idle(), state=ProcessState.READY, weight=w)
             for i, w in ((1, 1), (2, 5))]
    for _ in range(1000):
        sched.select_next(procs)
    assert max(abs(d) for d in sched._deficits.values()) <= 6


# ── 2. Dead letters ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mail_to_missing_or_dead_pid_is_dropped(kernel):
    sender = await kernel.spawn(Idle(), name="sender")
    peer = await kernel.spawn(Idle(), name="peer")
    assert (await kernel.ipc.send(sender.process_id, peer.process_id, "hi")).delivery_status == "DELIVERED"
    assert (await kernel.ipc.send(sender.process_id, 9999, "hi")).delivery_status == "DROPPED"
    await kernel.cancel(peer.process_id)
    assert (await kernel.ipc.send(sender.process_id, peer.process_id, "hi")).delivery_status == "DROPPED"
    assert kernel.ipc._queues.get(peer.process_id) is None   # its unread mail was discarded


@pytest.mark.asyncio
async def test_attached_mailboxes_get_the_guard(kernel):
    extra = IPCManager(kernel.settings, kernel.events)
    kernel.attach_ipc(extra)
    sender = await kernel.spawn(Idle(), name="sender")
    assert (await extra.send(sender.process_id, 4242, "x")).delivery_status == "DROPPED"


@pytest.mark.asyncio
async def test_standalone_ipc_still_accepts_any_pid():
    ipc = IPCManager()
    assert (await ipc.send(1, 9999, "x")).delivery_status == "DELIVERED"


# ── 3. REST cancel goes through the kernel ───────────────────────────────────
@pytest.mark.asyncio
async def test_rest_cancel_reclaims_locks_and_terminates(kernel, api):
    holder = await kernel.spawn(Idle(), name="holder")
    waiter = await kernel.spawn(Idle(), name="waiter")
    assert await kernel.sync.acquire_lock("db", holder.process_id)
    assert not await kernel.sync.acquire_lock("db", waiter.process_id)
    r = await api.post(f"/processes/{holder.process_id}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "TERMINATED"
    assert kernel.sync.get_lock("db").owner == waiter.process_id     # handed to the waiter


# ── 4. REST pause works between steps ────────────────────────────────────────
@pytest.mark.asyncio
async def test_rest_pause_and_resume_ready_process(kernel, api):
    p = await kernel.spawn(Idle(), name="ticker")
    assert p.state == ProcessState.READY
    r = await api.post(f"/processes/{p.process_id}/pause")
    assert r.status_code == 200 and r.json()["state"] == "WAITING"
    with pytest.raises(asyncio.TimeoutError):                       # paused: loop idles, never schedules it
        await asyncio.wait_for(kernel.run(max_steps=5), 0.3)
    assert p.resource_usage.steps == 0
    r = await api.post(f"/processes/{p.process_id}/resume")
    assert r.json()["state"] == "READY"
    await kernel.run(max_steps=3)
    assert p.resource_usage.steps == 3


@pytest.mark.asyncio
async def test_rest_pause_of_finished_process_is_rejected(kernel, api):
    p = await kernel.spawn(Idle(), name="gone")
    await kernel.cancel(p.process_id)
    r = await api.post(f"/processes/{p.process_id}/pause")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_process_manager_pause_handles_ready(kernel):
    p = await kernel.spawn(Idle(), name="ready")
    await kernel.pm.pause(p.process_id)
    assert p.state == ProcessState.WAITING
