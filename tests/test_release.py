"""Offline safety tests: model GCS generations and actual Cloud Run state."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import release as r
from scripts.smoke_http import SameOriginRedirect
from urllib.request import Request


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.serial = 0
        self.conflicts = 0

    def read(self, name):
        generation, value = self.objects.get(name, (0, None))
        return generation, deepcopy(value)

    def write(self, name, value, generation):
        current, _ = self.read(name)
        if name == r.STATE_OBJECT and self.conflicts:
            self.conflicts -= 1
            raise r.Conflict('another process won the compare-and-swap')
        if current != generation:
            raise r.Conflict('generation mismatch')
        self.serial += 1
        self.objects[name] = (self.serial, deepcopy(value))
        return self.serial

    def state(self):
        return self.read(r.STATE_OBJECT)[1]


def service():
    return {'metadata': {'name': r.SERVICE, 'labels': {
                'owner': 'dictionary-team', 'commit-sha': 'old-commit',
                'gcb-build-id': 'old-build', 'gcb-trigger-id': 'old-trigger'}},
            'spec': {'template': {'spec': {'containers': [{'env': [
                {'name': 'SECRET_KEY', 'valueFrom': {'secretKeyRef': {
                    'name': 'okinawago-flask-secret-key', 'key': '1'}}}]}]}}},
            'status': {'traffic': [{'revisionName': 'old-production', 'percent': 100},
                                   {'revisionName': 'another-preview', 'tag': 'existing',
                                    'url': 'https://existing---service.a.run.app'}]}}


def record(build_id='new-build'):
    return dict(commit_sha='a' * 40, build_id=build_id, attempt=f'attempt-{build_id}',
                trigger_id=r.TRIGGER_ID,
                image=r.REPOSITORY + '@sha256:' + 'a' * 64, digest='sha256:' + 'a' * 64,
                suffix='b-' + build_id, revision=r.SERVICE + '-b-' + build_id,
                tag='b-' + build_id)


class ModelCloud(r.Cloud):
    """Execute the real verify/cleanup/traffic logic against in-memory resources."""
    def __init__(self):
        super().__init__()
        self.current = service()
        self.revisions = {}
        self.promotions = []
        self.deploy_failure = False
        self.http_failure = False
        self.bad_digest = False
        self.wrong_tag = False
        self.unknown_mutation = False
        self.cleanup_failure = False
        self.smoke_hook = lambda: None
        self.checked_urls = []

    def run(self, *args, mutation=False):
        if args[:2] == ('services', 'describe'):
            return deepcopy(self.current)
        if args[:2] == ('revisions', 'describe'):
            return deepcopy(self.revisions[args[2]])
        if args[:2] == ('services', 'update'):
            if self.deploy_failure:
                raise RuntimeError('deployment failed')
            for arg in args:
                if arg.startswith('--update-labels='):
                    self.current['metadata']['labels'].update(
                        pair.split('=', 1) for pair in arg.split('=', 1)[1].split(','))
            revision = r.SERVICE + '-' + next(a.split('=', 1)[1] for a in args if a.startswith('--revision-suffix='))
            image = next(a.split('=', 1)[1] for a in args if a.startswith('--image='))
            tag = next(a.split('=', 1)[1] for a in args if a.startswith('--tag='))
            self.revisions[revision] = {'metadata': {'name': revision, 'labels': {
                'serving.knative.dev/service': r.SERVICE}}, 'status': {
                    'imageDigest': 'wrong' if self.bad_digest else image,
                    'conditions': [{'type': 'Ready', 'status': 'True'}]}}
            self.current['status']['traffic'].append({
                'revisionName': 'other-revision' if self.wrong_tag else revision,
                'tag': tag, 'url': f'https://{tag}---service.a.run.app'})
            return deepcopy(self.current)
        if args[:2] == ('services', 'update-traffic'):
            for arg in args:
                if arg.startswith('--to-revisions='):
                    revision = arg.split('=', 1)[1].removesuffix('=100')
                    self.promotions.append(revision)
                    self.current['status']['traffic'] = [
                        {**t, 'percent': 0} for t in self.current['status']['traffic']]
                    self.current['status']['traffic'].append({'revisionName': revision, 'percent': 100})
                    if self.unknown_mutation:
                        self.uncertain = True
                        raise RuntimeError('traffic update timed out after server accepted it')
                if arg.startswith('--remove-tags='):
                    if self.cleanup_failure:
                        raise RuntimeError('tag cleanup failed')
                    tag = arg.split('=', 1)[1]
                    for t in self.current['status']['traffic']:
                        if t.get('tag') == tag:
                            t.pop('tag')
                            t.pop('url', None)
            return deepcopy(self.current)
        raise AssertionError(f'Unexpected command: {args}')

    def smoke(self, url):
        self.checked_urls.append(url)
        self.smoke_hook()
        if self.http_failure:
            raise RuntimeError('definition missing')

    def tags(self):
        return {t['tag']: t['revisionName'] for t in self.current['status']['traffic'] if 'tag' in t}


class ReleaseSafetyTest(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStorage()
        self.cloud = ModelCloud()
        self.record = record()
        self.output = io.StringIO()
        self.stdout_redirect = redirect_stdout(self.output)
        self.stdout_redirect.__enter__()
        self.addCleanup(self.stdout_redirect.__exit__, None, None, None)
        self.stderr_redirect = redirect_stderr(self.output)
        self.stderr_redirect.__enter__()
        self.addCleanup(self.stderr_redirect.__exit__, None, None, None)

    def release(self, promote=True, build_record=None, order=None):
        return r.Release(self.cloud, self.storage, build_record or self.record,
                         order or ['2026-10-26T01:00:00.000000000Z', 'new-build'],
                         promote, lock_wait=0)

    def assert_no_switch(self):
        self.assertEqual([], self.cloud.promotions)
        self.assertEqual({'old-production': 100}, r.traffic(self.cloud.current))

    def test_deployment_failure_cannot_switch_and_is_recorded(self):
        self.cloud.deploy_failure = True
        release = self.release()
        with self.assertRaisesRegex(RuntimeError, 'deployment failed'):
            release.execute()
        self.assert_no_switch()
        saved = self.storage.read(release.record_name)[1]
        self.assertEqual({'old-production': 100}, saved['previous_traffic'])
        self.assertEqual(self.record['digest'], saved['digest'])
        self.assertEqual('complete', saved['cleanup'])
        self.assertIsNone(self.storage.state()['owner'])

    def test_http_failure_keeps_old_traffic_and_removes_only_own_tag(self):
        self.cloud.http_failure = True
        release = self.release()
        with self.assertRaisesRegex(RuntimeError, 'definition missing'):
            release.execute()
        self.assert_no_switch()
        self.assertEqual({'existing': 'another-preview'}, self.cloud.tags())
        self.assertEqual('failed', self.storage.read(release.record_name)[1]['phase'])

    def test_success_promotes_only_digest_verified_and_http_checked_revision(self):
        release = self.release()
        release.execute()
        self.assertEqual([self.record['revision']], self.cloud.promotions)
        self.assertEqual([f'https://{self.record["tag"]}---service.a.run.app'], self.cloud.checked_urls)
        self.assertEqual({self.record['revision']: 100}, r.traffic(self.cloud.current))
        self.assertEqual({'existing': 'another-preview'}, self.cloud.tags())
        self.assertEqual(self.record['revision'], self.storage.state()['last_promoted']['revision'])
        self.assertIsNone(self.storage.state()['owner'])

    def test_deploy_refreshes_tracking_labels_and_preserves_unrelated_labels(self):
        self.record.update(commit_sha='b' * 40, build_id='this-execution-build')
        self.release().execute()
        self.assertEqual({
            'owner': 'dictionary-team', 'commit-sha': 'b' * 40,
            'gcb-build-id': 'this-execution-build',
            'gcb-trigger-id': '166433e9-9b3d-4554-b92d-0d8c4e2aceb3',
        }, self.cloud.current['metadata']['labels'])

    def test_main_generates_bounded_distinct_names_and_persists_full_identities(self):
        first_build = '12345678-1234-1234-1234-123456789abc'
        second_build = '12345678-1234-1234-1234-123456789abd'
        first_attempt, second_attempt = 'a' * 31 + '1', 'a' * 31 + '2'
        cases = [(first_build, first_attempt), (first_build, second_attempt),
                 (second_build, first_attempt)]
        tags, revisions = set(), set()
        for build_id, attempt in cases:
            with self.subTest(build_id=build_id, attempt=attempt), tempfile.TemporaryDirectory() as directory:
                sha = 'b' * 40
                build = dict(id=build_id, projectId=r.PROJECT, buildTriggerId=r.TRIGGER_ID,
                             createTime='2026-10-26T00:00:00Z',
                             substitutions={'COMMIT_SHA': sha, 'BRANCH_NAME': 'main'})
                image_file = Path(directory) / 'image.json'
                image_file.write_text(json.dumps(dict(
                    tag=f'{r.REPOSITORY}:{sha}-{build_id}', digest='sha256:' + 'b' * 64)))
                args = ['release.py', '--build-id', build_id, '--commit-sha', sha,
                        '--bucket', 'release-state-bucket', '--image-file', str(image_file)]
                with patch('sys.argv', args), patch.dict(r.os.environ, {'RELEASE_PROJECT': r.PROJECT}), \
                        patch.object(r, 'gcloud', return_value=json.dumps(build)), \
                        patch.object(r, 'Cloud', return_value=self.cloud), \
                        patch.object(r, 'Storage', return_value=self.storage), \
                        patch.object(r.uuid, 'uuid4', return_value=r.uuid.UUID(hex=attempt)):
                    r.main()
                saved = self.storage.read(f'release/records/{build_id}/{attempt}.json')[1]
                self.assertEqual(build_id, saved['build_id'])
                self.assertEqual(attempt, saved['attempt'])
                self.assertEqual('verified_without_promotion', saved['phase'])
                self.assertLessEqual(len(r.SERVICE) + len(saved['tag']), 46)
                self.assertLessEqual(len(saved['revision']), 63)
                for field in ['tag', 'suffix', 'revision']:
                    self.assertRegex(saved[field], r'^[a-z][a-z0-9-]*[a-z0-9]$')
                self.assertNotEqual(saved['tag'], saved['suffix'])
                self.assertEqual(f'{r.SERVICE}-{saved["suffix"]}', saved['revision'])
                self.assertEqual(saved['revision'], saved['observed_revision'])
                self.assertIn(f'https://{saved["tag"]}---', saved['tag_url'])
                tags.add(saved['tag'])
                revisions.add(saved['revision'])
        self.assertEqual(len(cases), len(tags))
        self.assertEqual(len(cases), len(revisions))
        self.assert_no_switch()

    def test_real_cli_failure_records_diagnostics_and_retains_lock(self):
        original_run = self.cloud.run
        def run(*args, mutation=False):
            if args[:2] == ('services', 'update'):
                return r.Cloud.run(self.cloud, *args, mutation=mutation)
            return original_run(*args, mutation=mutation)
        result = subprocess.CompletedProcess([], 1, stdout='service definition must stay private',
                                             stderr='ERROR: Combined traffic tag and service name cannot exceed 46 characters.')
        release = self.release()
        with patch.object(self.cloud, 'run', side_effect=run), \
                patch.object(r.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'gcloud run services update failed \\(exit 1\\)'):
                release.execute()
        saved = self.storage.read(release.record_name)[1]
        self.assertIn('cannot exceed 46 characters', saved['error'])
        self.assertTrue(self.cloud.uncertain)
        self.assertIsNotNone(self.storage.state()['owner'])
        self.assertNotIn(result.stdout, self.output.getvalue())
        self.assert_no_switch()

    def test_verify_only_leaves_production_and_watermark_unchanged(self):
        self.release(promote=False).execute()
        self.assert_no_switch()
        self.assertTrue(self.cloud.checked_urls)
        self.assertIsNone(self.storage.state()['watermark'])
        self.assertEqual({'existing': 'another-preview'}, self.cloud.tags())

    def test_existing_tag_is_never_reassigned_or_deleted_even_on_name_collision(self):
        self.record['tag'] = 'existing'
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.release().execute()
        self.assert_no_switch()
        self.assertEqual({'existing': 'another-preview'}, self.cloud.tags())
        self.assertFalse(self.cloud.revisions)

    def test_digest_or_tag_mismatch_can_never_promote(self):
        for attribute in ['bad_digest', 'wrong_tag']:
            with self.subTest(attribute=attribute):
                self.cloud = ModelCloud()
                self.storage = MemoryStorage()
                setattr(self.cloud, attribute, True)
                with self.assertRaises(RuntimeError):
                    self.release().execute()
                self.assert_no_switch()
                if attribute == 'wrong_tag':
                    self.assertEqual('other-revision', self.cloud.tags()[self.record['tag']])
                    self.assertIsNotNone(self.storage.state()['owner'])

    def test_lock_contender_cannot_deploy_or_release_another_owners_lock(self):
        owner = r.Lock(self.storage, {'build_id': 'other', 'attempt': 'other'}, wait=0)
        owner.acquire()
        original = self.storage.read(r.STATE_OBJECT)
        with self.assertRaisesRegex(RuntimeError, 'lock wait timed out'):
            self.release().execute()
        self.assertEqual(original, self.storage.read(r.STATE_OBJECT))
        self.assert_no_switch()
        self.assertFalse(self.cloud.revisions)

    def test_generation_race_is_retried_with_bounded_wait(self):
        self.storage.conflicts = 1
        clock = [0]
        def sleep(seconds):
            clock[0] += seconds
        lock = r.Lock(self.storage, {'attempt': 'winner'}, wait=6,
                      sleep=sleep, clock=lambda: clock[0])
        lock.acquire()
        self.assertEqual({'attempt': 'winner'}, self.storage.state()['owner'])
        self.assertLessEqual(clock[0], 6)
        lock.release()

    def test_newer_build_blocks_late_old_build_before_deployment(self):
        self.release().execute()
        revisions = deepcopy(self.cloud.revisions)
        old = self.release(build_record=record('old-build'),
                           order=['2026-10-26T00:00:00.000000000Z', 'old-build'])
        old.execute()
        self.assertEqual([self.record['revision']], self.cloud.promotions)
        self.assertEqual(revisions, self.cloud.revisions)
        self.assertEqual('superseded', self.storage.read(old.record_name)[1]['phase'])

    def test_two_releases_cannot_overlap_during_http_check(self):
        competitor = self.release(build_record=record('competitor'))
        def try_competitor():
            with self.assertRaisesRegex(RuntimeError, 'lock wait timed out'):
                competitor.execute()
        self.cloud.smoke_hook = try_competitor
        self.release().execute()
        self.assertEqual([self.record['revision']], self.cloud.promotions)
        self.assertNotIn(record('competitor')['revision'], self.cloud.revisions)

    def test_stolen_lock_is_not_released_and_blocks_promotion_and_tag_cleanup(self):
        def replace_owner():
            generation, state = self.storage.read(r.STATE_OBJECT)
            state['owner'] = {'attempt': 'someone-else'}
            self.storage.write(r.STATE_OBJECT, state, generation)
        self.cloud.smoke_hook = replace_owner
        with self.assertRaisesRegex(RuntimeError, 'ownership lost'):
            self.release().execute()
        self.assert_no_switch()
        self.assertEqual({'attempt': 'someone-else'}, self.storage.state()['owner'])
        self.assertIn(self.record['tag'], self.cloud.tags())

    def test_preview_change_after_http_is_rejected(self):
        def change_tag():
            for t in self.cloud.current['status']['traffic']:
                if t.get('tag') == self.record['tag']:
                    t['revisionName'] = 'someone-else'
        self.cloud.smoke_hook = change_tag
        with self.assertRaisesRegex(RuntimeError, 'expected revision'):
            self.release().execute()
        self.assert_no_switch()
        self.assertEqual('someone-else', self.cloud.tags()[self.record['tag']])

    def test_production_drift_during_preview_cannot_be_overwritten(self):
        def external_switch():
            for t in self.cloud.current['status']['traffic']:
                if t.get('percent') == 100:
                    t['revisionName'] = 'operator-selected-revision'
        self.cloud.smoke_hook = external_switch
        with self.assertRaisesRegex(RuntimeError, 'changed during verification'):
            self.release().execute()
        self.assertEqual([], self.cloud.promotions)
        self.assertEqual({'operator-selected-revision': 100}, r.traffic(self.cloud.current))
        self.assertEqual({'existing': 'another-preview'}, self.cloud.tags())

    def test_unknown_switch_outcome_retains_lock_and_order_fence(self):
        self.cloud.unknown_mutation = True
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            self.release().execute()
        self.assertIsNotNone(self.storage.state()['owner'])
        self.assertIsNotNone(self.storage.state()['watermark'])
        self.assertIn(self.record['tag'], self.cloud.tags())
        # Server may already have switched: old builds must remain blocked.
        with self.assertRaisesRegex(RuntimeError, 'lock wait timed out'):
            self.release(build_record=record('old')).execute()
        self.assertEqual([self.record['revision']], self.cloud.promotions)

    def test_cleanup_failure_preserves_original_error_and_recovery_record(self):
        self.cloud.http_failure = True
        self.cloud.cleanup_failure = True
        release = self.release()
        with self.assertRaisesRegex(RuntimeError, 'definition missing'):
            release.execute()
        self.assertIn('Cleanup failed', self.output.getvalue())
        saved = self.storage.read(release.record_name)[1]
        self.assertIn('tag cleanup failed', saved['cleanup_errors'][0])
        self.assertEqual('definition missing', saved['error'])
        self.assertIsNotNone(self.storage.state()['owner'])
        self.assert_no_switch()

    def test_record_write_failure_before_deploy_cannot_change_production(self):
        original = self.storage.write
        def fail_deploy_record(name, value, generation):
            if name != r.STATE_OBJECT and value.get('phase') == 'deploying':
                raise RuntimeError('journal unavailable')
            return original(name, value, generation)
        self.storage.write = fail_deploy_record
        with self.assertRaisesRegex(RuntimeError, 'journal unavailable'):
            self.release().execute()
        self.assert_no_switch()
        self.assertFalse(self.cloud.revisions)

    def test_missing_service_and_wrong_secret_reference_fail_closed(self):
        self.cloud.current['spec']['template']['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']['key'] = 'latest'
        with self.assertRaisesRegex(RuntimeError, 'reference'):
            self.release().execute()
        self.assert_no_switch()
        self.assertFalse(self.cloud.revisions)
        with patch.object(self.cloud, 'service', side_effect=RuntimeError('service not found')):
            with self.assertRaisesRegex(RuntimeError, 'service not found'):
                self.release(build_record=record('next')).execute()
        self.assert_no_switch()


class BoundaryTest(unittest.TestCase):
    def test_source_and_published_image_must_belong_to_this_main_build(self):
        build_id = '12345678-1234-1234-1234-123456789abc'
        sha = 'a' * 40
        valid_build = dict(id=build_id, projectId=r.PROJECT, createTime='2026-10-26T00:00:00Z',
                           buildTriggerId='166433e9-9b3d-4554-b92d-0d8c4e2aceb3',
                           substitutions={'COMMIT_SHA': sha, 'BRANCH_NAME': 'main'})
        valid_image = dict(tag=f'{r.REPOSITORY}:{sha}-{build_id}', digest='sha256:' + 'a' * 64)
        for invalid in ['branch', 'sha', 'project', 'trigger', 'image_tag', 'image_digest', None]:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                build, image = deepcopy(valid_build), deepcopy(valid_image)
                if invalid == 'branch':
                    build['substitutions']['BRANCH_NAME'] = 'feature'
                elif invalid == 'sha':
                    build['substitutions']['COMMIT_SHA'] = 'b' * 40
                elif invalid == 'project':
                    build['projectId'] = 'another-project'
                elif invalid == 'trigger':
                    build['buildTriggerId'] = '5127d15f-b34a-4066-9956-da3b828b207a'
                elif invalid == 'image_tag':
                    image['tag'] = 'some-other-build'
                elif invalid == 'image_digest':
                    image['digest'] = 'latest'
                image_file = Path(directory) / 'image.json'
                image_file.write_text(json.dumps(image))
                args = ['release.py', '--build-id', build_id, '--commit-sha', sha,
                        '--bucket', 'release-state-bucket', '--image-file', str(image_file)]
                with patch('sys.argv', args), patch.dict(r.os.environ, {'RELEASE_PROJECT': r.PROJECT}), \
                        patch.object(r, 'gcloud', return_value=json.dumps(build)), \
                        patch.object(r, 'Release') as release:
                    if invalid:
                        with self.assertRaises(RuntimeError):
                            r.main()
                        release.assert_not_called()
                    else:
                        r.main()
                        release.return_value.execute.assert_called_once()
                        generated = release.call_args.args[2]
                        self.assertLessEqual(len(generated['revision']), 63)
                        self.assertEqual(build_id, generated['build_id'])
                        self.assertLessEqual(len(r.SERVICE) + len(generated['tag']), 46)
                        self.assertFalse(release.call_args.args[4])  # safe CLI default
                        with patch.object(r, 'gcloud', return_value='{}') as deploy_cli:
                            r.Cloud().deploy(generated)
                        labels = next(arg.split('=', 1)[1] for arg in deploy_cli.call_args.args
                                      if arg.startswith('--update-labels='))
                        self.assertEqual({
                            'commit-sha': sha, 'gcb-build-id': build_id,
                            'gcb-trigger-id': valid_build['buildTriggerId'],
                        }, dict(pair.split('=', 1) for pair in labels.split(',')))

    def test_build_order_normalizes_fractional_seconds(self):
        self.assertLess(r.build_order('2026-10-26T00:00:00Z', 'b'),
                        r.build_order('2026-10-26T00:00:00.001Z', 'a'))
        self.assertEqual(r.build_order('2026-10-26T00:00:00.1Z', 'a'),
                         r.build_order('2026-10-26T00:00:00.100000000Z', 'a'))

    def test_storage_uses_pinned_reads_and_conditional_writes(self):
        storage = r.Storage('release-state-bucket')
        with patch.object(storage, 'request', side_effect=[{'generation': '42'}, {'owner': None},
                                                           {'generation': '43'}]) as request:
            self.assertEqual((42, {'owner': None}), storage.read('release/state.json'))
            self.assertEqual(43, storage.write('release/state.json', {}, 42))
        self.assertIn('generation=42', request.call_args_list[1].args[1])
        self.assertIn('ifGenerationMatch=42', request.call_args_list[2].args[1])
        self.assertIn('release%2Fstate.json', request.call_args_list[2].args[1])

    def test_cloud_switch_has_explicit_revision_and_no_latest_or_iam_flags(self):
        cloud = r.Cloud()
        with patch.object(r, 'gcloud', return_value='{}') as cli:
            cloud.deploy(record())
            cloud.promote(record()['revision'])
        deploy = cli.call_args_list[0].args
        switch = cli.call_args_list[1].args
        self.assertIn('--no-traffic', deploy)
        self.assertFalse(any(a.startswith(('--clear-labels', '--remove-labels')) for a in deploy))
        self.assertEqual(('run', 'services', 'update'), deploy[:3])
        self.assertIn('--to-revisions=' + record()['revision'] + '=100', switch)
        self.assertFalse(any(a.startswith(('--to-latest', '--set-secrets', '--service-account',
                                           '--allow-unauthenticated')) for a in deploy + switch))

    def test_command_failure_retains_uncertain_mutation_state(self):
        cloud = r.Cloud()
        with patch.object(r, 'gcloud', side_effect=RuntimeError('timeout')):
            with self.assertRaises(RuntimeError):
                cloud.promote('tested-revision')
        self.assertTrue(cloud.uncertain)

    def test_run_failure_reports_operation_exit_and_redacted_stderr_only(self):
        error = ('WARNING: Authorization: Bearer header-credential\n'
                 'WARNING: access_token=access-credential refresh_token=refresh-credential\n'
                 'WARNING: ya29.oauth-credential\n'
                 'apiVersion: serving.knative.dev/v1\nkind: Service\n'
                 'spec:\n  private-definition: private-config-value\n'
                 'ERROR: (gcloud.run.services.update) Combined traffic tag and service name cannot exceed 46 characters.\n'
                 '{"spec": {"private-definition": "json-config-value"}}')
        result = subprocess.CompletedProcess([], 2, stdout='stdout-config-and-token', stderr=error)
        cloud = r.Cloud()
        with patch.object(r.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                cloud.deploy(record())
        message = str(caught.exception)
        self.assertIn('gcloud run services update failed (exit 2)', message)
        self.assertIn('Combined traffic tag and service name cannot exceed 46 characters.', message)
        for private in ['header-credential', 'access-credential', 'refresh-credential',
                        'oauth-credential', 'private-config-value', 'json-config-value', result.stdout]:
            self.assertNotIn(private, message)
        self.assertTrue(cloud.uncertain)

    def test_run_timeout_reports_operation_and_partial_stderr_with_unknown_exit(self):
        timeout = subprocess.TimeoutExpired('private-command-arguments', 300,
                                            output=b'private-service-definition',
                                            stderr=b'ERROR: connection closed; access_token=private-token')
        cloud = r.Cloud()
        with patch.object(r.subprocess, 'run', side_effect=timeout):
            with self.assertRaises(RuntimeError) as caught:
                cloud.promote('verified-revision')
        message = str(caught.exception)
        self.assertIn('gcloud run services update-traffic timed out after 300s (exit unknown)', message)
        self.assertIn('connection closed', message)
        for private in ['private-command-arguments', 'private-service-definition', 'private-token']:
            self.assertNotIn(private, message)
        self.assertTrue(cloud.uncertain)

    def test_auth_failure_does_not_expose_captured_output(self):
        result = subprocess.CompletedProcess([], 1, stdout='private-token', stderr='private-auth-diagnostic')
        with patch.object(r.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                r.gcloud('auth', 'print-access-token')
        self.assertIn('exit 1', str(caught.exception))
        self.assertNotIn(result.stdout, str(caught.exception))
        self.assertNotIn(result.stderr, str(caught.exception))

    def test_smoke_never_follows_redirect_to_production_or_another_origin(self):
        handler = SameOriginRedirect()
        request = Request('https://preview---service.a.run.app/')
        for url in ['https://okinawago.app/', 'http://preview---service.a.run.app/']:
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, 'external redirect'):
                handler.redirect_request(request, None, 302, '', {}, url)
        redirected = handler.redirect_request(request, None, 302, '', {},
                                              'https://preview---service.a.run.app/search-results/')
        self.assertIn('/search-results/', redirected.full_url)


if __name__ == '__main__':
    unittest.main()
