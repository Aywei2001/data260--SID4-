"""Verify the hw8 TAG in temporary containers; never edit application source.

Run from code/: python verify_hw8.py
Requires Git, Docker Desktop (Linux engine), and Docker Compose.
Host uses only Python's standard library. Output defaults to
reports/hw08/verification.json in the submitted repository.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
import zipfile


# Executed in a disposable API container using its installed dependencies.
# Sources of the three agents come from git archive of the exact tagged commit.
CONTAINER_CHECKS = r'''
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from uuid import UUID, uuid4

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import KafkaAdminClient, NewTopic
sys.path.insert(0, '/app')
from hw7_authentication import send_request

checks = []
def check(name, test):
    try:
        detail = test()
        checks.append({'name': name, 'passed': True, 'detail': detail})
    except Exception as error:
        checks.append({'name': name, 'passed': False,
                       'detail': f'{type(error).__name__}: {error}'})

def api():
    with urllib.request.urlopen('http://127.0.0.1:8439/openapi.json', timeout=10) as response:
        schema = json.load(response)
    paths = schema['paths']
    assert any('recall-notices' in path for path in paths), paths.keys()
    return 'FastAPI serves an OpenAPI schema with recall routes'

def round_trip():
    fields = {'name': 'Smoke recall', 'description': 'Verification test',
              'unique_code': 'SMOKE_' + uuid4().hex[:12].upper(),
              'quantity': 3, 'related_entity_id': 1}
    created = send_request('CREATE_GROCERY_RECALL_NOTICE', fields, timeout=30)
    assert created.get('success') is True, created
    notice_id = created['grocery_recall_notice_id']
    UUID(notice_id)
    found = send_request('GET_GROCERY_RECALL_NOTICE',
                         {'grocery_recall_notice_id': notice_id}, timeout=30)
    assert found.get('success') is True, found
    notice = found['grocery_recall_notice']
    assert notice['grocery_recall_notice_id'] == notice_id, found
    assert all(notice.get(key) == value for key, value in fields.items()), found
    assert created.get('correlation_id') and found.get('correlation_id')
    # send_request only returns responses whose correlation matches its request.
    return {'notice_id': notice_id, 'create_correlation_id': created['correlation_id'],
            'get_correlation_id': found['correlation_id'], 'fields_round_trip': True}

def create_topics():
    admin = KafkaAdminClient(bootstrap_servers='kafka:19092')
    try:
        definitions = {'s1339_inbox': 1, 's1339_tasks': 2,
                       's1339_drafts': 1, 's1339_final': 1,
                       's1339_dead_letter': 1}
        existing = set(admin.list_topics())
        missing = [NewTopic(name, count, 1) for name, count in definitions.items()
                   if name not in existing]
        if missing:
            admin.create_topics(missing)
        return definitions
    finally:
        admin.close()

def listen(topic):
    reader = KafkaConsumer(bootstrap_servers='kafka:19092', group_id=None,
                           enable_auto_commit=False)
    partitions = reader.partitions_for_topic(topic)
    if not partitions:
        reader.close()
        raise RuntimeError(f'Missing topic: {topic}')
    assigned = [TopicPartition(topic, p) for p in sorted(partitions)]
    reader.assign(assigned)
    reader.seek_to_end(*assigned)
    for partition in assigned:
        reader.position(partition)
    return reader

def receive(reader, cid, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for batch in reader.poll(timeout_ms=500).values():
            for record in batch:
                message = json.loads(record.value)
                if message.get('correlation_id') == cid:
                    return message
    raise TimeoutError(f'No matching message for {cid}')

processes = []
handles = []
producer = None
try:
    check('fastapi_starts', api)
    check('kafka_create_get_round_trip', round_trip)
    check('pipeline_topics', create_topics)
    producer = KafkaProducer(bootstrap_servers='kafka:19092', acks='all',
                             value_serializer=lambda value: json.dumps(value).encode())
    env = dict(os.environ, KAFKA_PREFIX='s1339',
               KAFKA_BOOTSTRAP_SERVERS='kafka:19092', WRITER_DELAY_SECONDS='0',
               ORDERING_PARTITION0_DELAY='0', MAX_PROCESSING_ATTEMPTS='3',
               IDEMPOTENCY_DB=str(Path(WORK) / 'smoke-idempotency.sqlite3'))
    def start_agents():
        for stage in ('planner', 'writer', 'reviewer'):
            path = Path(WORK) / (stage + '.log')
            handle = path.open('w')
            handles.append(handle)
            process = subprocess.Popen([sys.executable, '-u', str(Path(WORK) / (stage + '.py'))],
                                        cwd=WORK, env=env, stdout=handle,
                                        stderr=subprocess.STDOUT)
            processes.append((stage, process, path))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if all(f'{stage.upper()} READY' in path.read_text(errors='replace')
                   for stage, process, path in processes):
                return 'Three separate agent processes reached READY'
            for stage, process, path in processes:
                if process.poll() is not None:
                    raise RuntimeError(f'{stage} exited: {path.read_text(errors="replace")[-2000:]}')
            time.sleep(0.5)
        raise TimeoutError('Agents did not all become ready within 60 seconds')
    check('three_agents_start', start_agents)

    def publish(topic, message, partition=None):
        producer.send(topic, value=message,
                      key=message['correlation_id'].encode(),
                      partition=partition).get(timeout=15)

    def pipeline():
        reader = listen('s1339_final')
        cid = str(uuid4())
        try:
            publish('s1339_inbox', {'correlation_id': cid,
                'question': 'What should a grocery store do after a supplier recall?'})
            result = receive(reader, cid)
            assert isinstance(result.get('status'), str) and result['status'], result
            assert isinstance(result.get('answer'), str) and result['answer'].strip(), result
            assert result['correlation_id'] == cid
            return {'correlation_preserved': True, 'final_result': result}
        finally:
            reader.close()
    check('question_reaches_final_topic', pipeline)

    def duplicate():
        reader = listen('s1339_final')
        cid = str(uuid4())
        message = {'correlation_id': cid, 'question': 'Duplicate smoke question'}
        try:
            publish('s1339_inbox', message)
            publish('s1339_inbox', message)
            receive(reader, cid)
            deadline = time.monotonic() + 10
            skipped = False
            while time.monotonic() < deadline:
                log = (Path(WORK) / 'planner.log').read_text(errors='replace')
                skipped = f'DUPLICATE SKIP correlation_id={cid}' in log
                for batch in reader.poll(timeout_ms=300).values():
                    for record in batch:
                        assert json.loads(record.value).get('correlation_id') != cid, 'Duplicate final result'
            assert skipped, 'Missing explicit duplicate-skip evidence'
            return {'correlation_id': cid, 'duplicate_skipped': True,
                    'extra_final_results_during_10_seconds': 0}
        finally:
            reader.close()
    check('duplicate_replay_is_skipped', duplicate)

    def poison():
        dlq = listen('s1339_dead_letter')
        final = listen('s1339_final')
        bad_id, good_id = str(uuid4()), str(uuid4())
        plan = ['Identify the product and affected lot from the recall notice.',
                'Describe inventory isolation and sale blocking.',
                'Describe notification, disposition, and documentation.']
        try:
            publish('s1339_tasks', {'correlation_id': bad_id,
                    'question': 'Invalid task missing plan'}, partition=0)
            publish('s1339_tasks', {'correlation_id': good_id,
                    'question': 'Valid task behind poison', 'plan': plan}, partition=0)
            dead = receive(dlq, bad_id)
            assert dead.get('attempts') == 3 and dead.get('source_partition') == 0, dead
            assert dead.get('error'), dead
            result = receive(final, good_id)
            assert result.get('answer'), result
            return {'dead_letter_correlation_id': bad_id,
                    'later_valid_correlation_id': good_id, 'attempts': dead['attempts'],
                    'same_partition_made_progress': True}
        finally:
            dlq.close()
            final.close()
    check('poison_routes_to_dlq_and_later_task_completes', poison)
except Exception as error:
    checks.append({'name': 'smoke_setup', 'passed': False,
                   'detail': f'{type(error).__name__}: {error}'})
finally:
    for stage, process, path in processes:
        process.terminate()
    for stage, process, path in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for handle in handles:
        handle.close()
    if producer:
        producer.close(timeout=5)
    logs = {stage: path.read_text(errors='replace')[-15000:]
            for stage, process, path in processes}
    result = {'checks': checks, 'agent_logs': logs,
              'versions': {name: importlib.metadata.version(name)
                           for name in ('kafka-python', 'fastapi', 'pydantic')}}
    print('HW8_SMOKE_RESULT=' + json.dumps(result), flush=True)
'''


def command(args, cwd=None, env=None, timeout=120, input_text=None):
    result = subprocess.run(args, cwd=cwd, env=env, input=input_text,
                            text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]} exited {result.returncode}:\n{result.stdout[-6000:]}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output or repo / 'reports' / 'hw08' / 'verification.json'
    report = {
        'homework_number': 8, 'SID4': 1339, 'tag': 'hw8', 'commit_hash': None,
        'SEED': 1339, 'VERIFY_SEED': 261339,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'configuration': {'prefix': 's1339', 'agents': 'rule-based', 'model': None,
                          'broker_inside_docker': 'kafka:19092',
                          'scope': 'basic startup, request/response, pipeline, duplicate and DLQ smoke checks'},
        'checks': [],
        'not_run': ['forced consumer termination/recovery experiment',
                    '20-message two-Writer unkeyed/keyed ordering experiments',
                    'authenticated HTTP CREATE/GET'],
    }
    def record(name, passed, detail):
        report['checks'].append({'name': name, 'passed': passed, 'detail': detail})
        print(f'{"PASS" if passed else "FAIL"}: {name}', flush=True)

    compose = None
    environment = dict(os.environ, JWT_SECRET_KEY=secrets.token_hex(32))
    try:
        tag_commit = command(['git', '-C', str(repo), 'rev-parse',
                              'refs/tags/hw8^{commit}']).strip()
        report['commit_hash'] = tag_commit
        report['current_head'] = command(['git', '-C', str(repo), 'rev-parse', 'HEAD']).strip()
        record('hw8_tag_resolves', True, tag_commit)
        # Test tracked files in the tag, NOT uncommitted files in the working tree.
        archive = subprocess.run(['git', '-C', str(repo), 'archive', '--format=zip', tag_commit],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=60).stdout
        with tempfile.TemporaryDirectory(prefix='hw8-smoke-') as scratch:
            root = Path(scratch)
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                # Only ordinary repository files are needed; reject path traversal.
                for item in zipped.infolist():
                    resolved = (root / item.filename).resolve()
                    if not resolved.is_relative_to(root.resolve()):
                        raise ValueError('Unsafe archive path')
                zipped.extractall(root)
            code = root / 'code'
            required = ['compose.yaml', 'Dockerfile', 'requirements-docker.txt',
                        'hw7_authentication.py', 'homework_demo.py',
                        'planner.py', 'writer.py', 'reviewer.py', 'send_question.py']
            missing = [name for name in required if not (code / name).is_file()]
            if missing:
                raise RuntimeError(f'Files missing from hw8 tag: {missing}')
            record('tag_contains_application_files', True, required)
            project = 'hw8smoke' + secrets.token_hex(4)
            config = (code / 'compose.yaml').read_text(encoding='utf-8-sig')
            # Change only the TEMPORARY deployment config: avoid current ports,
            # image tags, networks and volumes. All tests use internal listeners.
            for old, new in (
                ('127.0.0.1:9092:9092', '127.0.0.1::9092'),
                ('127.0.0.1:8439:8439', '127.0.0.1::8439'),
                ('s1339-recall-app:local', project + ':local'),
            ):
                if old not in config:
                    raise RuntimeError(f'Compose template changed; expected {old}')
                config = config.replace(old, new)
            (code / 'compose.smoke.yaml').write_text(config, encoding='utf-8')
            compose = ['docker', 'compose', '-p', project, '-f', str(code / 'compose.smoke.yaml')]
            try:
                command(['docker', 'info'], timeout=30)
                command(compose + ['config', '--quiet'], env=environment)
                print('Building and starting isolated tagged application...', flush=True)
                command(compose + ['up', '--build', '-d'], env=environment, timeout=1200)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    logs = command(compose + ['logs', '--no-color', 'worker'], env=environment)
                    if 'Consumer is ready and listening' in logs:
                        break
                    time.sleep(1)
                else:
                    raise TimeoutError('Part 1 worker did not become ready')
                record('tagged_compose_system_starts', True, 'Worker reached READY in isolated project')
                sources = {name: (code / name).read_text(encoding='utf-8-sig')
                           for name in ('planner.py', 'writer.py', 'reviewer.py')}
                encoded = base64.b64encode(json.dumps(sources).encode()).decode()
                # Temporary scripts are created inside the temporary container;
                # neither host application files nor the tagged source are edited.
                bootstrap = (
                    'import base64,json,tempfile\nfrom pathlib import Path\n'
                    f'sources=json.loads(base64.b64decode({encoded!r}))\n'
                    'with tempfile.TemporaryDirectory(prefix="hw8-check-") as WORK:\n'
                    '    for name,source in sources.items():\n'
                    '        Path(WORK,name).write_text(source,encoding="utf-8")\n'
                    f'    exec(compile({CONTAINER_CHECKS!r},"<smoke-checks>","exec"))\n'
                )
                log = command(compose + ['exec', '-T', 'api', 'python', '-u', '-'],
                              env=environment, input_text=bootstrap, timeout=420)
                marker = 'HW8_SMOKE_RESULT='
                lines = [line for line in log.splitlines() if line.startswith(marker)]
                if not lines:
                    raise RuntimeError('Container returned no structured results:\n' + log[-4000:])
                results = json.loads(lines[-1][len(marker):])
                report['configuration']['package_versions'] = results['versions']
                report['agent_logs'] = results['agent_logs']
                for check in results['checks']:
                    record(check['name'], check['passed'], check['detail'])
            finally:
                if compose:
                    try:
                        report['service_logs'] = command(
                            compose + ['logs', '--no-color', '--tail', '100', 'worker', 'api'],
                            env=environment)[-25000:]
                    except Exception as error:
                        report['service_logs_error'] = str(error)
                    try:
                        command(compose + ['down', '--volumes', '--remove-orphans'],
                                env=environment, timeout=120)
                        record('temporary_containers_cleaned_up', True, project)
                    except Exception as error:
                        record('temporary_containers_cleaned_up', False, str(error))
    except Exception as error:
        record('verification_execution', False, f'{type(error).__name__}: {error}')
    report['passed'] = bool(report['checks']) and all(c['passed'] for c in report['checks'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Wrote {output.resolve()}; overall={"PASS" if report["passed"] else "FAIL"}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
