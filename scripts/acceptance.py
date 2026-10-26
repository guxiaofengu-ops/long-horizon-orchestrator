#!/usr/bin/env python3
"""Opt-in, real-time CLI acceptance ladder. Uses the installed skill, not this checkout.

Run with --execute. This makes real Codex model calls at start/checkpoints/end.
No model is called by the monitoring loop. Evidence stays in --output.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


def atomic(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def events(path):
    result = []
    if path.exists():
        for line in path.read_text(errors='replace').splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def workload(args):
    """Low-CPU synthetic numerical fixture, with real elapsed-time evidence."""
    started = time.time()
    mono = time.monotonic()
    progress = Path(args.progress)
    step = 0
    while True:
        elapsed = time.monotonic() - mono
        step += 1
        sample = sum((0.5 * x - 2 * x) ** 2 for x in range(128)) / 128
        record = {'step': step, 'phase': args.phase, 'utc': utc(), 'elapsed_seconds': elapsed, 'mse': sample}
        with progress.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        print(json.dumps(record), flush=True)
        if elapsed >= args.seconds and (not args.handoff_file or Path(args.handoff_file).exists()):
            break
        time.sleep(max(.2, min(1 if step < 2 else 30, args.seconds - elapsed)))
    atomic(Path(args.result), {'fixture': 'synthetic-numerical-soak', 'phase': args.phase,
                              'started_at': started, 'finished_at': time.time(),
                              'elapsed_seconds': time.monotonic() - mono,
                              'minimum_seconds': args.seconds, 'progress_steps': step,
                              'mse': sample, 'ok': True})


CONFIG = ['model_providers.openai.supports_websockets=false',
          'sandbox_mode="danger-full-access"', 'approval_policy="never"']


def codex_turn(output, thread_id, prompt, cwd):
    command = ['codex', 'exec', 'resume', thread_id, prompt, '--json', '--skip-git-repo-check']
    for config in CONFIG:
        command.extend(['-c', config])
    with output.open('w') as f:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=f, stderr=subprocess.STDOUT, timeout=300)
    parsed = events(output)
    if result.returncode or not any(x.get('type') == 'turn.completed' for x in parsed):
        raise RuntimeError(f'Codex turn did not complete: {output}')


def command_json(cli, state, *args):
    result = subprocess.run([sys.executable, str(cli), '--state-dir', str(state), *args],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def ladder(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cli = Path(args.installed).expanduser().resolve() / 'scripts/lho'
    durations = [float(x) for x in args.durations.split(',')]
    if not durations or any(x <= 0 for x in durations):
        raise ValueError('positive durations required')
    state = output / 'state'
    summary_path = output / 'ladder.json'
    summary = {'status': 'RUNNING', 'started_at': utc(), 'pid': os.getpid(),
               'thread_id': args.thread_id, 'installed_skill': str(cli.parent.parent),
               'planned_seconds': durations, 'stages': [], 'model_calls_in_monitor_loop': 0}
    atomic(summary_path, summary)
    fixture = output / 'acceptance-fixture.py'
    shutil.copyfile(__file__, fixture)
    run_id = None
    try:
        for index, duration in enumerate(durations):
            folder = output / f'stage-{index + 1}-{int(duration)}s'
            folder.mkdir(exist_ok=False)
            contract_path = folder / 'contract.json'
            run_id = f'accept-{index+1}-{int(duration)}s-{int(time.time())}'
            phases = []
            for name, seconds in [('inference', duration), ('training', 5)]:
                phases.append({'name': name, 'command': [sys.executable, str(fixture), 'workload',
                              '--phase', name, '--seconds', str(seconds), '--progress', f'{name}.jsonl',
                              '--result', f'{name}.json', '--handoff-file', str(folder / 'initial-turn-ended')], 'progress_jsonl': f'{name}.jsonl',
                               'checkpoint': name == 'inference', 'timeout_seconds': seconds + 120,
                               'success': [{'type': 'json', 'path': f'{name}.json',
                                            'required_keys': ['elapsed_seconds', 'ok', 'progress_steps']}]})
            contract = {'schema_version': 1, 'name': f'real-codex-{int(duration)}s',
                        'workspace': str(folder), 'preflight_steps': 2, 'phases': phases,
                        'loop': {'max_iterations': 1},
                        'budget': {'max_wall_seconds': duration + 1200, 'max_phase_runs': 2,
                                   'max_failures': 1, 'max_log_bytes': 10000000},
                        'wakeup': {'mode': 'codex_exec', 'thread_id': args.thread_id,
                                   'codex_bin': shutil.which('codex'), 'timeout_seconds': 300, 'config': CONFIG}}
            atomic(contract_path, contract)
            stage = {'run_id': run_id, 'seconds': duration, 'workspace': str(folder), 'status': 'STARTING',
                     'started_at': utc(), 'state_dir': str(state)}
            summary['stages'].append(stage)
            atomic(summary_path, summary)
            prompt = (
                'Use $long-horizon-orchestrator for this authorized local acceptance fixture. '
                f'The exact contract is {contract_path}. Launch it using Python {sys.executable} '
                f'and the installed CLI {cli}, --state-dir {state}, start {contract_path} '
                f'--run-id {run_id} --wait-preflight. Inspect only the first two steps and launch log, '
                'then END THE TURN immediately. Do not wait for completion or poll. '
                'Persist these instructions in this conversation: on a CHECKPOINT notification '
                f'for this run, read the report, verify inference.json elapsed_seconds >= {duration}, '
                f'run the same CLI with --state-dir {state} resume {run_id} --approve-checkpoint, '
                'then END THE TURN. On SUCCEEDED, verify both artifacts and write a JSON receipt '
                f'at {folder / "codex-verified.json"} containing run_id, inference_elapsed_seconds, '
                'training_elapsed_seconds, and verified=true; then END THE TURN. '
                'On failure, report it and end the turn without retrying or repairing the fixture. '
                'Never create other jobs, agents, automations, or modify the installed skill.'
            )
            codex_turn(folder / 'codex-start.jsonl', args.thread_id, prompt, folder)
            atomic(folder / 'initial-turn-ended', {'utc': utc()})
            stage['initial_turn_completed_at'] = utc()
            atomic(summary_path, summary)
            deadline = time.monotonic() + duration + 1500
            last_snapshot = 0
            restarted_at = 0
            while time.monotonic() < deadline:
                status = command_json(cli, state, 'status', run_id)
                stage.update(status)
                stage['observed_at'] = utc()
                if time.monotonic() - last_snapshot >= 30:
                    with (output / 'monitor.jsonl').open('a') as f:
                        f.write(json.dumps({'utc': utc(), 'run_id': run_id, 'status': status}) + '\n')
                    last_snapshot = time.monotonic()
                atomic(summary_path, summary)
                with sqlite3.connect(state / 'state.sqlite3') as db:
                    lease_until = db.execute('SELECT lease_until FROM runs WHERE id=?', (run_id,)).fetchone()[0]
                if status['status'] == 'RUNNING' and (lease_until or 0) < time.time() - 15 and time.monotonic() - restarted_at > 30:
                    with (folder / 'watchdog.log').open('a') as out:
                        subprocess.Popen([sys.executable, str(cli), '--state-dir', str(state), 'supervise', run_id],
                                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
                    restarted_at = time.monotonic()
                if status['wake_status'] == 'dispatch_unknown':
                    raise RuntimeError(f'Unconfirmed Codex wakeup: {run_id}')
                if status['status'] in {'FAILED', 'CANCELLED', 'BUDGET_EXCEEDED'}:
                    raise RuntimeError(f'Failed stage: {status}')
                receipt = folder / 'codex-verified.json'
                if status['status'] == 'SUCCEEDED' and status['wake_status'] == 'sent':
                    if not receipt.exists():
                        raise RuntimeError(f'Missing actual Codex verification receipt: {folder}')
                    verified = json.loads(receipt.read_text())
                    inference = json.loads((folder / 'inference.json').read_text())
                    if not verified.get('verified') or inference['elapsed_seconds'] < duration:
                        raise RuntimeError('Duration or Codex verification failed')
                    stage['receipt'] = verified
                    stage['finished_at'] = utc()
                    stage['status'] = 'PASSED'
                    atomic(folder / 'report.json', command_json(cli, state, 'report', run_id, '--json'))
                    atomic(summary_path, summary)
                    break
                time.sleep(2)
            else:
                raise TimeoutError(f'Stage watchdog deadline exceeded: {run_id}')
        summary['status'] = 'PASSED'
    except BaseException as exc:
        summary['status'] = 'FAILED'
        summary['error'] = f'{type(exc).__name__}: {exc}'
        if run_id:
            try:
                subprocess.run([sys.executable, str(cli), '--state-dir', str(state), 'cancel', run_id], timeout=30)
            except Exception:
                pass
        raise
    finally:
        summary['updated_at'] = utc()
        atomic(summary_path, summary)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('workload')
    p.add_argument('--phase', required=True)
    p.add_argument('--seconds', type=float, required=True)
    p.add_argument('--progress', required=True)
    p.add_argument('--result', required=True)
    p.add_argument('--handoff-file')
    p = sub.add_parser('ladder')
    p.add_argument('--installed', default='~/.codex/skills/long-horizon-orchestrator')
    p.add_argument('--output', required=True)
    p.add_argument('--thread-id', required=True)
    p.add_argument('--durations', default='10,60,300,18010')
    p.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.action == 'workload':
        workload(args)
    elif args.execute:
        ladder(args)
    else:
        parser.error('Real model calls require --execute')


if __name__ == '__main__':
    main()
