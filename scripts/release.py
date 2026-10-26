"""Fail-closed Cloud Run release orchestration. No third-party Python packages."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

PROJECT = 'okinawago-dictionary'
SERVICE = 'okinawago-dictionary-app'
REGION = 'asia-southeast1'
TRIGGER_ID = '166433e9-9b3d-4554-b92d-0d8c4e2aceb3'
REPOSITORY = f'asia.gcr.io/{PROJECT}/{SERVICE}/{SERVICE}'
STATE_OBJECT = 'release/state.json'


class Conflict(RuntimeError):
    """A generation precondition failed; never retry a mutation blindly."""


def diagnostic_stderr(value):
    """Keep CLI diagnostics, redact credentials, and omit JSON/YAML resource dumps."""
    if isinstance(value, bytes):  # TimeoutExpired can carry bytes even with text=True.
        value = value.decode('utf-8', errors='replace')
    value = value or ''
    value = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', value)
    value = re.sub(r'(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', '[redacted authorization]', value)
    value = re.sub(r'''(?ix)["']?\b(?:access[_ -]?token|id[_ -]?token|refresh[_ -]?token|
                   client[_ -]?secret|authorization|secret_key)["']?\s*[:=]\s*["']?[^\s,"'}]+''',
                   '[redacted credential]', value)
    value = re.sub(r'\bya29\.[A-Za-z0-9._~-]+', '[redacted token]', value)
    value = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
                   '[redacted token]', value)
    lines = []
    resource_dump = False
    for line in value.splitlines():
        if re.match(r'^\s*(ERROR|WARNING):', line):
            resource_dump = False
        # Configuration belongs in neither logs nor exception messages. Resume
        # only at the next diagnostic marker after a structured-output section.
        if (re.search(r'[{}]', line) or line.lstrip().startswith('[') or
                re.match(r'^\s*(?:ERROR:\s*)?(?:apiVersion|kind|metadata|spec|status)\s*:', line)):
            prefix = line.split('{', 1)[0] if '{' in line else ''
            if not resource_dump:
                lines.append(prefix + '[structured output omitted]')
            resource_dump = True
        elif not resource_dump:
            lines.append(line)
    return '\n'.join(lines).strip()[-4000:] or '(no diagnostic stderr)'


def command(args, timeout=60, include_error=False, operation=None):
    # Capture configuration output: never print service env or access tokens.
    operation = operation or f'{args[0]} {args[1]}'
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        detail = f'; stderr: {diagnostic_stderr(error.stderr)}' if include_error else ''
        raise RuntimeError(f'{operation} timed out after {timeout}s (exit unknown){detail}') from None
    if result.returncode:
        detail = f'; stderr: {diagnostic_stderr(result.stderr)}' if include_error else ''
        raise RuntimeError(f'{operation} failed (exit {result.returncode}){detail}')
    return result.stdout.strip()


def gcloud(*args, timeout=60):
    cloud_run = args[:1] == ('run',)
    return command(['gcloud', *args, f'--project={PROJECT}', '--quiet'], timeout,
                   include_error=cloud_run, operation='gcloud ' + ' '.join(args[:3]))


class Storage:
    """GCS JSON API with generation-conditional writes, including lock release."""
    def __init__(self, bucket):
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', bucket) or bucket == 'SET_ME':
            raise ValueError('Configure a dedicated existing state bucket')
        self.bucket = bucket

    def request(self, method, url, body=None):
        token = gcloud('auth', 'print-access-token')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 412:
                raise Conflict('GCS generation changed') from None
            if error.code == 404 and method == 'GET':
                return None
            raise RuntimeError(f'GCS {method} failed: HTTP {error.code}') from None

    def read(self, name):
        base = f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{quote(name, safe="")}'
        metadata = self.request('GET', base)
        if metadata is None:
            return 0, None
        generation = int(metadata['generation'])
        # Pin the content read to the generation whose metadata we saw.
        value = self.request('GET', f'{base}?alt=media&generation={generation}')
        if value is None:
            raise Conflict('GCS object changed while reading')
        return generation, value

    def write(self, name, value, generation):
        url = (f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o'
               f'?uploadType=media&name={quote(name, safe="")}&ifGenerationMatch={generation}')
        result = self.request('POST', url, json.dumps(value).encode())
        return int(result['generation'])


def empty_state():
    return {'version': 1, 'owner': None, 'watermark': None, 'last_promoted': None}


class Lock:
    def __init__(self, storage, owner, wait=300, sleep=time.sleep, clock=time.monotonic):
        self.storage, self.owner, self.wait = storage, owner, wait
        self.sleep, self.clock = sleep, clock
        self.generation = None
        self.state = None

    def acquire(self):
        deadline = self.clock() + self.wait
        while True:
            try:
                generation, state = self.storage.read(STATE_OBJECT)
                state = state if state is not None else empty_state()
                if state.get('version') != 1 or 'owner' not in state or 'watermark' not in state:
                    raise RuntimeError('Invalid release state; manual recovery required')
                if state['owner'] is None:
                    state['owner'] = self.owner
                    new_generation = self.storage.write(STATE_OBJECT, state, generation)
                    self.generation, self.state = new_generation, state
                    return
            except Conflict:
                pass
            if self.clock() >= deadline:
                raise RuntimeError('Release lock wait timed out; no lock was taken or removed')
            self.sleep(min(5, max(0, deadline - self.clock())))

    def assert_owned(self):
        generation, state = self.storage.read(STATE_OBJECT)
        if generation != self.generation or state['owner'] != self.owner:
            raise RuntimeError('Release lock ownership lost; manual recovery required')

    def save(self):
        self.assert_owned()
        self.generation = self.storage.write(STATE_OBJECT, self.state, self.generation)

    def release(self):
        self.assert_owned()
        self.state['owner'] = None
        self.generation = self.storage.write(STATE_OBJECT, self.state, self.generation)


def build_order(created, build_id):
    # Cloud Build server createTime, normalized to nanoseconds for lexical order.
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z', created)
    if not match:
        raise ValueError('Invalid Cloud Build createTime')
    datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S')
    return [match[1] + '.' + (match[2] or '').ljust(9, '0') + 'Z', build_id]


def traffic(service):
    result = {}
    for entry in service['status'].get('traffic', []):
        if entry.get('percent', 0):
            revision = entry.get('revisionName')
            if not revision:
                raise RuntimeError('Production traffic is not resolved to named revisions')
            result[revision] = result.get(revision, 0) + entry['percent']
    if sum(result.values()) != 100:
        raise RuntimeError('Expected 100% resolved production traffic')
    return result


def check_secret(service):
    containers = service['spec']['template']['spec']['containers']
    if len(containers) != 1:
        raise RuntimeError('Expected a single-container service')
    env = {item['name']: item for item in containers[0].get('env', [])}
    reference = env.get('SECRET_KEY', {}).get('valueFrom', {}).get('secretKeyRef', {})
    # Cloud Run may use an alias whose actual name is in the secrets annotation.
    name = reference.get('name', '')
    annotations = service['spec']['template'].get('metadata', {}).get('annotations', {})
    aliases = annotations.get('run.googleapis.com/secrets', '')
    alias_map = dict(pair.split(':', 1) for pair in aliases.split(',') if ':' in pair)
    resolved = alias_map.get(name, name)
    expected = ('okinawago-flask-secret-key',
                f'projects/{PROJECT}/secrets/okinawago-flask-secret-key',
                'projects/429157770916/secrets/okinawago-flask-secret-key')
    if resolved not in expected or reference.get('key') != '1':
        raise RuntimeError('Expected existing SECRET_KEY reference to version 1; refusing to change it')


class Cloud:
    def __init__(self):
        self.uncertain = False

    def run(self, *args, mutation=False):
        if mutation:
            self.uncertain = True
        value = gcloud('run', *args, f'--region={REGION}', '--format=json', timeout=300)
        if mutation:
            self.uncertain = False
        return json.loads(value)

    def service(self):
        value = self.run('services', 'describe', SERVICE)
        if value['metadata']['name'] != SERVICE:
            raise RuntimeError('Wrong service')
        return value

    def deploy(self, record):
        # update cannot create a missing service. No IAM, env, secrets or runtime-SA flags.
        labels = (f'commit-sha={record["commit_sha"]},gcb-build-id={record["build_id"]},'
                  f'gcb-trigger-id={record["trigger_id"]}')
        self.run('services', 'update', SERVICE, f'--image={record["image"]}',
                 f'--revision-suffix={record["suffix"]}', f'--tag={record["tag"]}',
                 f'--update-labels={labels}', '--no-traffic', mutation=True)

    def verify(self, record):
        service = self.service()
        revision = self.run('revisions', 'describe', record['revision'])
        if revision['metadata']['name'] != record['revision']:
            raise RuntimeError('Wrong revision')
        if revision['metadata'].get('labels', {}).get('serving.knative.dev/service') != SERVICE:
            raise RuntimeError('Revision belongs to a different service')
        if not any(c.get('type') == 'Ready' and c.get('status') == 'True'
                   for c in revision['status'].get('conditions', [])):
            raise RuntimeError('Revision is not Ready')
        actual = revision['status'].get('imageDigest', '')
        if actual != record['image']:
            raise RuntimeError('Deployed image digest does not match the published image')
        matches = [t for t in service['status'].get('traffic', []) if t.get('tag') == record['tag']]
        if len(matches) != 1 or matches[0].get('revisionName') != record['revision']:
            raise RuntimeError('Tag does not point to the expected revision')
        url = matches[0].get('url', '')
        if not re.fullmatch(r'https://[a-z0-9-]+\.a\.run\.app', url):
            # Cloud Run also uses non-region-coded run.app hostnames.
            if not re.fullmatch(r'https://[a-z0-9.-]+\.run\.app', url):
                raise RuntimeError('Missing or unexpected tag URL')
        if not url.startswith(f'https://{record["tag"]}---'):
            raise RuntimeError('URL is not specific to this build tag')
        check_secret(service)
        record.update(observed_revision=revision['metadata']['name'], observed_digest=actual)
        return url

    def smoke(self, url):
        print(command([sys.executable, 'scripts/smoke_http.py', url,
                       '--startup-timeout', '90'], timeout=180, include_error=True), flush=True)

    def promote(self, revision):
        self.run('services', 'update-traffic', SERVICE,
                 f'--to-revisions={revision}=100', mutation=True)

    def cleanup(self, record):
        service = self.service()
        matches = [t for t in service['status'].get('traffic', []) if t.get('tag') == record['tag']]
        if not matches:
            return
        if len(matches) != 1 or matches[0].get('revisionName') != record['revision']:
            raise RuntimeError('Tag ownership mismatch; tag was not removed')
        self.run('services', 'update-traffic', SERVICE,
                 f'--remove-tags={record["tag"]}', mutation=True)


class Release:
    def __init__(self, cloud, storage, record, order, promote, lock_wait=300):
        self.cloud, self.storage, self.record = cloud, storage, record
        self.order, self.promote = order, promote
        self.lock = Lock(storage, {'build_id': record['build_id'], 'attempt': record['attempt']}, lock_wait)
        self.record_generation = 0
        self.record_name = f'release/records/{record["build_id"]}/{record["attempt"]}.json'

    def journal(self, phase, **fields):
        self.record.update(phase=phase, **fields)
        self.record['updated_at'] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(self.record, sort_keys=True), flush=True)
        self.record_generation = self.storage.write(self.record_name, self.record, self.record_generation)

    def execute(self):
        acquired = False
        self.deployed = False
        error = None
        try:
            self.journal('waiting_for_lock')
            self.lock.acquire()
            acquired = True
            watermark = self.lock.state['watermark']
            if watermark is not None and self.order <= watermark:
                self.journal('superseded')
            else:
                self.deploy_and_check()
        except BaseException as caught:
            error = caught
            try:
                self.journal('failed', error=str(caught))
            except Exception as journal_error:
                print(f'Record persistence failed: {journal_error}', file=sys.stderr)
        finally:
            cleanup_errors = []
            if acquired:
                try:
                    self.lock.assert_owned()
                    if self.cloud.uncertain:
                        raise RuntimeError('Cloud Run mutation outcome unknown; lock/tag retained for recovery')
                    if self.deployed:
                        self.cloud.cleanup(self.record)
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
                # Do not unlock an unknown mutation, failed cleanup, or lost ownership.
                if not cleanup_errors:
                    try:
                        self.journal(self.record['phase'], cleanup='complete')
                        self.lock.release()
                    except Exception as cleanup_error:
                        cleanup_errors.append(str(cleanup_error))
            if cleanup_errors:
                print('Cleanup failed: ' + '; '.join(cleanup_errors), file=sys.stderr)
                try:
                    self.journal(self.record['phase'], cleanup_errors=cleanup_errors)
                except Exception as journal_error:
                    print(f'Record persistence failed: {journal_error}', file=sys.stderr)
                if error is None:
                    error = RuntimeError('; '.join(cleanup_errors))
        if error is not None:
            raise error

    def deploy_and_check(self):
        service = self.cloud.service()  # must exist, including in verify-only mode
        check_secret(service)
        if any(t.get('tag') == self.record['tag'] for t in service['status'].get('traffic', [])):
            raise RuntimeError('Preview tag already exists; refusing to reuse it')
        previous = traffic(service)
        self.journal('deploying', previous_traffic=previous, order=self.order)
        # Mark before calling update: cleanup also runs after a partial failure.
        self.deployed = True
        self.cloud.deploy(self.record)
        url = self.cloud.verify(self.record)
        if traffic(self.cloud.service()) != previous:
            raise RuntimeError('Production traffic changed during preview deployment')
        self.journal('checking', tag_url=url)
        self.cloud.smoke(url)
        self.lock.assert_owned()
        if self.cloud.verify(self.record) != url or traffic(self.cloud.service()) != previous:
            raise RuntimeError('Preview or production traffic changed during verification')
        self.journal('verified')
        if self.promote:
            # Persist a conservative fence BEFORE the external traffic mutation.
            # A crash/ambiguous response must never let an older build overwrite it.
            self.lock.state['watermark'] = self.order
            self.lock.save()
            self.journal('promoting')
            self.cloud.promote(self.record['revision'])
            if traffic(self.cloud.service()) != {self.record['revision']: 100}:
                raise RuntimeError('Production switch could not be confirmed')
            self.journal('promoted', traffic_switch_confirmed=True)
            self.lock.state['last_promoted'] = deepcopy(self.record)
            self.lock.save()
        else:
            self.journal('verified_without_promotion')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-id', required=True)
    parser.add_argument('--commit-sha', required=True)
    parser.add_argument('--build-region', default='global')
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--promote', choices=['true', 'false'], default='false')
    parser.add_argument('--image-file', default='/workspace/release-image.json')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f-]{36}', args.build_id) or not re.fullmatch(r'[0-9a-f]{40}', args.commit_sha):
        parser.error('Expected Cloud Build UUID and full commit SHA')
    if os.environ.get('RELEASE_PROJECT') != PROJECT:
        parser.error('Release must run in the configured production project')
    build = json.loads(gcloud('builds', 'describe', args.build_id,
                              f'--region={args.build_region}', '--format=json'))
    if (build['id'] != args.build_id or build['projectId'] != PROJECT or
            build.get('buildTriggerId') != TRIGGER_ID or
            build.get('substitutions', {}).get('COMMIT_SHA') != args.commit_sha or
            build.get('substitutions', {}).get('BRANCH_NAME') != 'main'):
        raise RuntimeError('Build identity/source is not the expected production main build')
    published = json.loads(Path(args.image_file).read_text())
    expected_tag = f'{REPOSITORY}:{args.commit_sha}-{args.build_id}'
    if published['tag'] != expected_tag or not re.fullmatch(r'sha256:[0-9a-f]{64}', published['digest']):
        raise RuntimeError('Published image identity mismatch')
    attempt = uuid.uuid4().hex
    identity_hash = hashlib.sha256(f'{args.build_id}:{attempt}'.encode()).hexdigest()
    # Tag + service is limited to 46 characters, separately from the 63-character
    # revision-name limit. Keep full identities in the release record, not names.
    tag = 'p' + identity_hash[:20]
    suffix = 'r' + identity_hash[:32]
    record = dict(project=PROJECT, service=SERVICE, region=REGION,
                  commit_sha=args.commit_sha, build_id=args.build_id, build_region=args.build_region,
                  trigger_id=build['buildTriggerId'],
                  attempt=attempt, image=f'{REPOSITORY}@{published["digest"]}',
                  digest=published['digest'], suffix=suffix, revision=f'{SERVICE}-{suffix}', tag=tag,
                  promote=args.promote == 'true')
    Release(Cloud(), Storage(args.bucket), record, build_order(build['createTime'], args.build_id),
            args.promote == 'true').execute()


def interrupted(signum, frame):
    raise RuntimeError('Release interrupted; check records and lock before recovery')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Release failed: {error}', file=sys.stderr)
        sys.exit(1)
