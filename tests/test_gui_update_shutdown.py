import os
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from naga_control.gui.releases import Release
from naga_control.gui.version_panel import VersionPanel
from naga_control.gui.worker import CoroFactory, LoopWorker


def test_stalled_update_check_does_not_block_worker_shutdown(tmp_path: Path) -> None:
    qapp = cast(QApplication, QApplication.instance() or QApplication([]))
    worker = LoopWorker()
    worker.start()
    started, release, finished = (threading.Event() for _ in range(3))
    daemon_threads: list[bool] = []
    futures: list[Future[object]] = []

    def fetch() -> tuple[Release, ...]:
        daemon_threads.append(threading.current_thread().daemon)
        started.set()
        try:
            assert release.wait(5)
            return ()
        finally:
            finished.set()

    def run(factory: CoroFactory) -> None:
        futures.append(worker.submit(factory))

    panel = VersionPanel(
        run,
        settings=QSettings(str(tmp_path / "updates.ini"), QSettings.Format.IniFormat),
        current_version="0.3.0",
        fetcher=fetch,
    )
    try:
        panel.check_updates()
        assert started.wait(5)
        worker.stop(timeout=1)
        assert not finished.is_set()
        assert futures[0].cancelled()
        assert daemon_threads == [True]
        assert not worker.running
        qapp.processEvents()
        assert panel.stable_label.text() == "Not checked"
    finally:
        release.set()
        assert finished.wait(5)
        worker.stop()
        panel.close()
