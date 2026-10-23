import os
import random

import numpy as np
import pytest

# Render the voice in a thread during tests instead of spawning a worker process.
os.environ.setdefault("BLIP_VOICE_THREAD", "1")


@pytest.fixture(autouse=True)
def _seed():
    random.seed(1234)
    np.random.seed(1234)


def render(engine, seconds):
    """Run the audio callback offline and return the mono output."""
    from blip16.constants import BLOCK, SR

    out = np.zeros((BLOCK, 2), dtype=np.float32)
    chunks = []
    for _ in range(int(seconds * SR / BLOCK)):
        engine.cb(out, BLOCK, None, None)
        chunks.append(out[:, 0].copy())
    return np.concatenate(chunks)
