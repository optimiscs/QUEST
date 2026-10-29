from inference.gaia_scheduler import select_gpu


def test_scheduler_uses_idle_healthy_gpu_and_limits_capacity():
    assert select_gpu([8, 5, 0], lambda i: True) == 2
    assert select_gpu([8, 5, 0], lambda i: i != 2) == 1
    assert select_gpu([8, 8, 8], lambda i: True) is None


def test_scheduler_balances_24_slots():
    slots = [0, 0, 0]
    for _ in range(24):
        gpu = select_gpu(slots, lambda i: True)
        assert gpu is not None
        slots[gpu] += 1
    assert slots == [8, 8, 8]
    assert select_gpu(slots, lambda i: True) is None
