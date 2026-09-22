"""C review probe: deterministic sources; no live provider, database or LLM.

Usage: python calendar_probe.py --source PATH --before PATH --output PATH
The two code versions are loaded unchanged; only external fetch is stubbed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import importlib.util
import json
from pathlib import Path
import threading
from unittest.mock import patch

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TradingCalendarProvider

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    current = load(args.source / 'backend/app/data/trading_calendar.py', 'calendar_current')
    before = load(args.before, 'calendar_before')
    rows = [date(2025, 1, 2), date(2025, 1, 3)]
    tests = []

    current._shared_trade_dates = None
    barrier = threading.Barrier(8)
    def worker(_):
        barrier.wait(timeout=10)
        return current().get_trade_dates()
    with patch.object(current, '_load_from_akshare', return_value=rows) as fetch:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, range(8)))
        tests.append({'name': 'eight_default_instances_share_one_fetch', 'passed': fetch.call_count == 1 and all(x == rows for x in results), 'fetch_calls': fetch.call_count})
        results[0].clear()
        tests.append({'name': 'default_return_copy_does_not_mutate_shared_cache', 'passed': current().get_trade_dates() == rows})
        current().refresh()
        tests.append({'name': 'default_refresh_reloads_shared_cache', 'passed': fetch.call_count == 2, 'total_fetch_calls': fetch.call_count})

    isolated = [date(2024, 1, 2)]
    calls = []
    def injected_fetch():
        calls.append(1)
        return isolated
    injected = current(fetch=injected_fetch)
    tests.append({'name': 'injected_fetch_isolated_and_refreshable', 'passed': injected.get_trade_dates() == isolated and injected.refresh() == isolated and len(calls) == 2 and current().get_trade_dates() == rows})

    current._shared_trade_dates = None
    with patch.object(current, '_load_from_akshare', side_effect=[RuntimeError('simulated source unavailable'), rows]) as fetch:
        try:
            current().get_trade_dates()
        except RuntimeError:
            pass
        retried = current().get_trade_dates()
        tests.append({'name': 'failed_initial_fetch_can_retry', 'passed': fetch.call_count == 2 and retried == rows})

    refresh_results = {}
    for label, cls in [('846c1cc_before', before), ('4a7402a_after', current)]:
        with patch.object(cls, '_load_from_akshare', return_value=rows) as fetch:
            provider = cls(trade_dates=[date(2020, 1, 2)])
            try:
                result = provider.refresh()
                refresh_results[label] = {'ok': result == rows, 'loader_calls': fetch.call_count}
            except Exception as exc:
                refresh_results[label] = {'ok': False, 'error': type(exc).__name__, 'message': str(exc), 'loader_calls': fetch.call_count}
    tests.append({'name': 'static_trade_dates_refresh_backward_compatibility', 'passed': refresh_results['4a7402a_after']['ok'], 'comparison': refresh_results})
    report = {'tested_SHA': '4a7402a35ec1a42a3a6964d9f351395d19315188',
              'scope': 'Deterministic calendar unit probe; not live AKShare/V8, browser, or MySQL evidence',
              'tests': tests, 'passed': sum(x['passed'] for x in tests), 'failed': sum(not x['passed'] for x in tests)}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report['failed'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
