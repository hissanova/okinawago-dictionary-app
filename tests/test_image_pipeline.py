"""Offline checks for image continuity, failures and shared Docker networking."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import check, publish_image
from scripts.release import REPOSITORY


class ImagePipelineTest(unittest.TestCase):
    def test_existing_image_is_checked_without_rebuild_or_deletion(self):
        calls = []
        containers = iter(['unit', 'server', 'http'])
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'create':
                return next(containers)
            if args[0] == 'inspect':
                return json.dumps([{'State': {'ExitCode': 0}}])
        with patch.object(check, 'docker', side_effect=docker), \
                patch('sys.argv', ['check.py', '--image', 'tested-image']), \
                patch.object(check.signal, 'signal'), redirect_stdout(io.StringIO()):
            self.assertEqual(0, check.main())
        self.assertFalse(any(c[0] in ('build', 'image') for c in calls))
        creates = [c for c in calls if c[0] == 'create']
        self.assertTrue(all('tested-image' in c for c in creates))
        self.assertIn('container:server', creates[-1])
        self.assertIn('scripts/smoke_http.py', creates[-1])
        self.assertTrue(all('-p' not in c for c in creates))
        self.assertEqual({'unit', 'server', 'http'}, {c[-1] for c in calls if c[0] == 'rm'})

    def test_container_failure_is_nonzero_even_if_docker_start_returns_success(self):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'create':
                return 'failed-unit'
            if args[0] == 'inspect':
                return json.dumps([{'State': {'ExitCode': 1}}])
        with patch.object(check, 'docker', side_effect=docker), \
                patch('sys.argv', ['check.py', '--image', 'tested-image']), \
                patch.object(check.signal, 'signal'), redirect_stderr(io.StringIO()):
            self.assertEqual(1, check.main())
        self.assertEqual(1, len([c for c in calls if c[0] == 'create']))
        self.assertIn(('rm', '-f', 'failed-unit'), calls)

    def publish(self, directory, remote_digest, local_digest):
        image = REPOSITORY + ':' + 'a' * 40 + '-12345678-1234-1234-1234-123456789abc'
        output = Path(directory) / 'published.json'
        def gcloud(*args, **kwargs):
            return remote_digest if args[:2] == ('container', 'images') else ''
        info = json.dumps([{'RepoDigests': [REPOSITORY + '@' + local_digest]}])
        with patch('sys.argv', ['publish_image.py', image, '--output', str(output)]), \
                patch.object(publish_image, 'gcloud', side_effect=gcloud), \
                patch.object(publish_image.subprocess, 'run') as push, \
                patch.object(publish_image.subprocess, 'check_output', return_value=info):
            publish_image.main()
        push.assert_called_once_with(['docker', 'push', image], check=True, timeout=600)
        return output

    def test_publish_records_only_the_registry_digest_of_the_checked_image(self):
        digest = 'sha256:' + 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            output = self.publish(directory, digest, digest)
            self.assertEqual(digest, json.loads(output.read_text())['digest'])

    def test_changed_registry_tag_cannot_supply_a_deployment_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                self.publish(directory, 'sha256:' + 'b' * 64, 'sha256:' + 'a' * 64)
            self.assertFalse((Path(directory) / 'published.json').exists())

    def test_invalid_registry_digest_cannot_supply_a_deployment_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'valid digest'):
                self.publish(directory, 'not-a-digest', 'sha256:' + 'a' * 64)
            self.assertFalse((Path(directory) / 'published.json').exists())


if __name__ == '__main__':
    unittest.main()
