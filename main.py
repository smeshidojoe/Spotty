import ctypes
import sys
from ctypes import wintypes

from spotty.core.constants import INSTANCE_MUTEX, IPC_NAME

ERROR_ALREADY_EXISTS = 183

# Держим хэндл мьютекса в глобальной переменной: он должен жить до конца
# процесса, иначе сборщик закроет его и второй запуск пройдёт свободно.
_INSTANCE_MUTEX = None


def _is_only_instance():
    """True — мы единственный экземпляр; False — Spotty уже запущен."""
    global _INSTANCE_MUTEX
    try:
        k = ctypes.windll.kernel32
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        _INSTANCE_MUTEX = k.CreateMutexW(None, False, INSTANCE_MUTEX)
        return k.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        return True         # ошибку ctypes не превращаем в запрет запуска


def _ask_running_to_show():
    """Второй запуск (ярлык, меню «Пуск») просит работающий Spotty открыть строку."""
    try:
        from PySide6.QtNetwork import QLocalSocket
        socket = QLocalSocket()
        socket.connectToServer(IPC_NAME)
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
    except Exception:
        pass


if __name__ == "__main__":
    from spotty.core import updater

    # Самоприменение обновления: этот же exe (Spotty-new.exe) запущен с флагом
    # --apply-update <старый_exe>. Ждёт выхода старого, подменяет его собой и
    # запускает. Обрабатываем ДО мьютекса — это не «второй экземпляр».
    if "--apply-update" in sys.argv:
        try:
            index = sys.argv.index("--apply-update")
            updater.apply_self_update(sys.argv[index + 1]
                                      if index + 1 < len(sys.argv) else "")
        except Exception:
            pass
        sys.exit(0)

    # Второй экземпляр повесил бы второй значок в трее и второй хоткей —
    # вместо этого показываем строку первого и выходим.
    if not _is_only_instance():
        _ask_running_to_show()
        sys.exit(0)

    # Скачанный, но не установленный архив не трогаем: он ждёт кнопки
    # «Перезапустить и обновить» (см. updater.pending_version). Убираем только
    # копию нового exe, оставшуюся от уже применённого обновления.
    try:
        updater.cleanup_applied()
    except Exception:
        pass

    from spotty.app import main
    sys.exit(main())
