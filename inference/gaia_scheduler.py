"""Select a healthy 4B endpoint with available task capacity."""


def select_gpu(slots, healthy, limit=8):
    available = [i for i in range(len(slots)) if slots[i] < limit and healthy(i)]
    return min(available, key=lambda i: (slots[i], i)) if available else None
