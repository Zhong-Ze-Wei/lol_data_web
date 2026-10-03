"""独立于应用配置的采集进程锁，迁移与采集使用同一锁实现。"""

import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class PipelineLock:
    """OS 释放进程锁；即使程序崩溃也没有需要手动删除的过期锁。"""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.handle.write(b'\0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise AlreadyRunning('已有采集/导入任务正在运行，本次未启动') from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.handle.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
