import os
import time

import pymupdf
import pytest
from PyQt5 import QtWidgets

from modules.common.batch_runner import BatchRunner


def _wait(app, cond, timeout=30):
    t = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.01)
        assert time.time() - t < timeout


def test_hub_builds_and_all_pages_exist(qapp):
    import hub_window
    w = hub_window.MainHubWindow()
    assert w.stack.count() >= 9


def test_runner_cancel_and_error_isolation(qapp):
    btn, pb = QtWidgets.QPushButton(), QtWidgets.QProgressBar()
    r = BatchRunner(None, btn, pb)
    out = []
    r.start([1, 0, 2], lambda i: 1 / i, on_finished=lambda o, c: out.append((o, c)))
    _wait(qapp, lambda: out)
    outcomes, cancelled = out[0]
    assert [o.error is None for o in outcomes] == [True, False, True] and not cancelled
    assert btn.isEnabled()

    out.clear()
    r.start(range(100), lambda i: time.sleep(0.02),
            on_item=lambda i, o: r.cancel() if i == 3 else None,
            on_finished=lambda o, c: out.append((o, c)))
    _wait(qapp, lambda: out)
    assert out[0][1] and len(out[0][0]) < 100


@pytest.fixture
def mocked_dialogs(monkeypatch, tmp_path):
    msgs = []
    out = tmp_path / "out"
    out.mkdir()
    mb = QtWidgets.QMessageBox
    monkeypatch.setattr(mb, "information", staticmethod(lambda *a, **k: msgs.append(a[2])))
    monkeypatch.setattr(mb, "warning", staticmethod(lambda *a, **k: msgs.append(a[2])))
    monkeypatch.setattr(mb, "question", staticmethod(lambda *a, **k: mb.Yes))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(out)))
    return msgs, out


def _three_same_name(make_pdf):
    return [make_pdf("same.pdf", 2, folder=f"s{i}") for i in range(3)]


def test_rotator_batch_no_overwrites(qapp, make_pdf, mocked_dialogs):
    from modules.pdf_rotator.rotator_widget import PDFBatchRotatorWidget
    msgs, out = mocked_dialogs
    paths = _three_same_name(make_pdf)
    w = PDFBatchRotatorWidget()
    w.append_files(paths)
    w.file_rotations = {p: 90 for p in paths}
    w.process_batch_rotate()
    _wait(qapp, lambda: msgs)
    files = sorted(os.listdir(out))
    assert files == ["same_rotated.pdf", "same_rotated_1.pdf", "same_rotated_2.pdf"]
    assert all(pymupdf.open(str(out / f))[0].rotation == 90 for f in files)


def test_cropper_batch_skips_files_without_frame(qapp, make_pdf, mocked_dialogs, monkeypatch):
    from modules.pdf_cropper.cropper_widget import PDFBatchCropperWidget
    msgs, out = mocked_dialogs
    paths = _three_same_name(make_pdf)
    w = PDFBatchCropperWidget()
    w.append_files(paths)
    w.file_crop_rects = {p: pymupdf.Rect(10, 10, 200, 200) for p in paths[:2]}

    def fake_exec(self):
        self._pick = next(b for b in self.buttons() if "Пропустити" in b.text())
        return 0
    mb = QtWidgets.QMessageBox
    monkeypatch.setattr(mb, "exec_", fake_exec)
    monkeypatch.setattr(mb, "clickedButton", lambda self: self._pick)
    w.process_batch_crop()
    _wait(qapp, lambda: msgs)
    assert len(os.listdir(out)) == 2
    assert "без рамки): 1" in msgs[-1]


def test_compressor_batch(qapp, make_pdf, mocked_dialogs):
    from modules.pdf_compressor.compressor_widget import PDFBatchCompressorWidget
    msgs, out = mocked_dialogs
    paths = _three_same_name(make_pdf)
    w = PDFBatchCompressorWidget()
    w.append_files(paths)
    w.process_batch_compress()
    _wait(qapp, lambda: msgs)
    assert len(os.listdir(out)) == 3
    assert w.results_table.rowCount() == 3


def test_window_geometry_is_remembered(qapp):
    import hub_window
    from modules.common.settings import app_settings
    app_settings().remove("window/geometry")
    w = hub_window.MainHubWindow()
    w.resize(1111, 777)
    w.show()
    w.close()
    w2 = hub_window.MainHubWindow()
    assert (w2.width(), w2.height()) == (1111, 777)


def test_shortcuts_switch_tabs_and_open_file_dialog(qapp, monkeypatch):
    import hub_window
    w = hub_window.MainHubWindow()
    # Активація вікна в offscreen недоступна - викликаємо сам шорткат.
    w.shortcuts["Ctrl+5"].activated.emit()
    assert w.stack.currentIndex() == 5
    assert w.sidebar.btn_group.checkedId() == 5
    w.shortcuts["Ctrl+0"].activated.emit()
    assert w.stack.currentIndex() == 0

    # Ctrl+O викликає діалог додавання файлів активного інструмента
    calls = []
    for idx, widget in ((4, w.cropper_widget), (7, w.merge_widget)):
        name = "add_files" if idx == 4 else "add_files_dialog"
        monkeypatch.setattr(widget, name, lambda *a, n=idx: calls.append(n))
        w.go_to_module(idx)
        w.shortcuts["Ctrl+O"].activated.emit()
    assert calls == [4, 7]
