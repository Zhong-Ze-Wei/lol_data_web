"""旧脚本名保留为每日采集入口；不会改写 config.py 或自动无限扫 ID。"""

from scripts.pipeline import main


if __name__ == '__main__':
    raise SystemExit(main(['daily']))
