from modules.common.eta import EtaEstimator


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_eta_none_until_enough_data():
    c = Clock()
    e = EtaEstimator(10, clock=c)
    assert e.remaining_seconds() is None
    c.t = 1
    e.advance(1)
    assert e.remaining_seconds() is None  # < MIN_ELAPSED


def test_eta_average_speed_and_skip():
    c = Clock()
    e = EtaEstimator(10, clock=c)
    c.t = 10
    e.advance(2)                     # 5 с / одиниця
    assert e.remaining_seconds() == 40
    e.skip(4)                        # залишилось 4 замість 8
    assert e.remaining_seconds() == 20


def test_eta_never_negative():
    c = Clock()
    e = EtaEstimator(1, clock=c)
    c.t = 5
    e.advance(3)
    assert e.remaining_seconds() == 0


def test_format():
    f = EtaEstimator.format
    assert f(None) == "" and f(2) == "< 5 с" and f(42) == "≈ 42 с"
    assert f(200) == "≈ 3 хв 20 с" and f(3900) == "≈ 1 год 05 хв"
