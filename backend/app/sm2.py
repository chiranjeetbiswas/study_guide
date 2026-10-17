from dataclasses import dataclass
from datetime import date, timedelta

MIN_EASE = 1.3

# SM-2 grades answers 0-5 and treats 3+ as a pass. With two buttons we use the
# grades that mean "recalled it" (4) and "failed to recall" (1).
QUALITY_KNEW = 4
QUALITY_DIDNT = 1


@dataclass
class Schedule:
    ease_factor: float
    interval_days: int
    repetitions: int
    due_date: date


def next_schedule(ease_factor: float, interval_days: int, repetitions: int, knew: bool, today: date) -> Schedule:
    quality = QUALITY_KNEW if knew else QUALITY_DIDNT

    if quality >= 3:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval_days * ease_factor)
        repetitions += 1
    else:
        # Failed: start the card's streak over and see it again tomorrow
        repetitions = 0
        interval = 1

    ease_factor = max(MIN_EASE, ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

    return Schedule(ease_factor, interval, repetitions, today + timedelta(days=interval))
