"""Small, bounded variations for automatic game input; no blocking sleeps."""
import random


def profile(previous=None, rng=random):
    offsets = [(x, y) for x in range(-3, 4) for y in range(-2, 3)
               if (x, y) != (0, 0) and (x, y) != previous]
    return dict(offset=rng.choice(offsets),
                reaction=rng.uniform(.15, .45),
                pause=rng.uniform(.12, .35) + (rng.uniform(.3, .8) if rng.random() < .18 else 0),
                speed=rng.uniform(1800, 3200),
                duration_floor=rng.uniform(.16, .28),
                hold=rng.uniform(.055, .115))


def scroll_interval(rng=random):
    return rng.randint(180, 320) if rng.random() < .12 else rng.randint(30, 95)
