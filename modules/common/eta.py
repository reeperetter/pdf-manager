"""Оцінка часу, що залишився, за середньою швидкістю обробки."""
import time


class EtaEstimator:
    """Рахує швидкість у 'одиницях' (сторінки) від створення об'єкта.

    advance(n) - n одиниць оброблено; skip(n) - n одиниць пропущено (не
    враховуються ні в швидкості, ні в залишку). remaining_seconds()
    повертає None, доки даних замало (треба хоч одну одиницю і >= MIN_ELAPSED
    секунд), щоб не показувати стрибкоподібні неправдиві значення."""

    MIN_ELAPSED = 3.0

    def __init__(self, total, clock=time.monotonic):
        self.total = max(0, int(total))
        self.done = 0
        self._clock = clock
        self._start = clock()

    def advance(self, n=1):
        self.done += n

    def skip(self, n):
        self.total = max(0, self.total - n)

    def remaining_seconds(self):
        elapsed = self._clock() - self._start
        if self.done <= 0 or elapsed < self.MIN_ELAPSED:
            return None
        left = max(0, self.total - self.done)
        return elapsed / self.done * left

    @staticmethod
    def format(seconds):
        """'≈ 3 хв 20 с', '≈ 1 год 05 хв', '< 5 с'."""
        if seconds is None:
            return ""
        s = int(round(seconds))
        if s < 5:
            return "< 5 с"
        if s < 60:
            return f"≈ {s} с"
        m, s = divmod(s, 60)
        if m < 60:
            return f"≈ {m} хв {s:02d} с"
        h, m = divmod(m, 60)
        return f"≈ {h} год {m:02d} хв"
