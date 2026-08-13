"""The stack watcher (T87): span compression and the end-to-end thread."""

import sys
import time

from pd2bot.runlog.sampler import SpanWriter, StackSampler, stack_signature


def collect():
    spans = []
    return spans, lambda wall, dur, sig: spans.append((wall, dur, sig))


def test_identical_samples_compress_into_one_span():
    spans, emit = collect()
    w = SpanWriter(emit, min_span_s=0.25)
    for i in range(10):
        w.sample(t=i * 0.1, wall=100.0 + i * 0.1, sig="a.py:1:f")
    w.sample(t=1.0, wall=101.0, sig="b.py:2:g")  # the change flushes
    assert spans == [(100.0, 1.0, "a.py:1:f")]


def test_short_spans_are_churn_and_never_written():
    spans, emit = collect()
    w = SpanWriter(emit, min_span_s=0.25)
    w.sample(t=0.0, wall=100.0, sig="a.py:1:f")
    w.sample(t=0.1, wall=100.1, sig="b.py:2:g")  # 0.1s of a — dropped
    w.sample(t=0.2, wall=100.2, sig="c.py:3:h")  # 0.1s of b — dropped
    assert spans == []


def test_close_flushes_the_open_span():
    """A stall still running when the process ends must not vanish —
    the last span is precisely the one a hung run needs on the record."""
    spans, emit = collect()
    w = SpanWriter(emit, min_span_s=0.25)
    w.sample(t=0.0, wall=100.0, sig="stuck.py:9:blocked")
    w.sample(t=15.0, wall=115.0, sig="stuck.py:9:blocked")
    w.close()
    assert spans == [(100.0, 15.0, "stuck.py:9:blocked")]


def test_the_signature_reads_innermost_first():
    sig = stack_signature(sys._getframe())
    first = sig.split(" < ")[0]
    assert first.startswith("test_sampler.py:")
    assert first.endswith(":test_the_signature_reads_innermost_first")


def _linger():
    time.sleep(0.6)


def test_the_sampler_names_the_line_a_stall_lives_on(tmp_path):
    """End to end: a main thread that blocks for 0.6 s appears in the
    sample file with this module's name on the span."""
    path = tmp_path / "samples.log"
    sampler = StackSampler(path, interval_s=0.02, min_span_s=0.2)
    sampler.start()
    try:
        _linger()  # the "stall": the sampler must catch us inside it
    finally:
        sampler.stop()
    text = path.read_text(encoding="utf-8")
    assert "_linger" in text, text
    assert "test_sampler.py" in text
