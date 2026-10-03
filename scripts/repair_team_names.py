"""显式范围、零 HTTP 的历史队名修复；默认只读审计。"""

import argparse
import json
import sqlite3
from pathlib import Path

from app.services.team_name_repair import TeamNameRepairError, repair_team_names
from scripts.pipeline_lock import AlreadyRunning


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--reports-dir', type=Path, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--result-ids', nargs='+', type=int, help='明确的正整数单局 ID，不能使用 all')
    scope.add_argument('--ids-file', type=Path, help='JSON 正整数列表；不接受候选清单对象或新名称')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--dry-run', action='store_true', help='仅审计（默认）')
    parser.add_argument('--wait-seconds', type=float, default=0, help='等待采集锁，0–60 秒')
    args = parser.parse_args(argv)
    try:
        ids = json.loads(args.ids_file.read_text(encoding='utf-8')) if args.ids_file else args.result_ids
        report = repair_team_names(args.database, args.raw_dir, args.reports_dir, result_ids=ids,
                                   apply=args.apply, wait_seconds=args.wait_seconds)
    except AlreadyRunning:
        print(json.dumps({'status': 'already_running', 'error': '采集锁正在使用；未执行队名修复'}, ensure_ascii=False))
        return 3
    except (OSError, ValueError, TypeError, sqlite3.DatabaseError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({key: value for key, value in report.items() if key != 'records'}, ensure_ascii=False, indent=2))
    return 2 if report['blocked'] or report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
