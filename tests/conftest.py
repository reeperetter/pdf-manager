import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PyQt5 import QtCore, QtWidgets
    # Ізолюємо QSettings від налаштувань користувача.
    QtCore.QCoreApplication.setOrganizationName("pdf-manager-tests")
    QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat, QtCore.QSettings.UserScope,
                             tempfile.mkdtemp())
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope,
                             tempfile.mkdtemp())
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def make_pdf(tmp_path):
    """make_pdf(name, pages=2, toc=None) -> шлях до простого PDF."""
    def _make(name="a.pdf", pages=2, toc=None, folder=None):
        d = tmp_path / folder if folder else tmp_path
        d.mkdir(parents=True, exist_ok=True)
        path = str(d / name)
        doc = pymupdf.open()
        for i in range(pages):
            doc.new_page().insert_text((72, 72), f"Page {i + 1}")
        if toc:
            doc.set_toc(toc)
        doc.save(path)
        doc.close()
        return path
    return _make
