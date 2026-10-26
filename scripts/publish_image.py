"""Push the checked image and verify the digest resolved by the registry."""
import argparse
import json
from pathlib import Path
import re
import subprocess

if __package__:
    from .release import REPOSITORY, gcloud
else:
    from release import REPOSITORY, gcloud


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--output', default='/workspace/release-image.json')
    args = parser.parse_args()
    if not re.fullmatch(re.escape(REPOSITORY) + r':[0-9a-f]{40}-[0-9a-f-]{36}', args.image):
        parser.error('Expected the configured repository, full commit SHA and build ID')
    # Configure credentials in this build's HOME; do not depend on helpers that
    # happen to be installed in the separate Docker builder step image.
    gcloud('auth', 'configure-docker', 'asia.gcr.io')
    subprocess.run(['docker', 'push', args.image], check=True, timeout=600)
    digest = gcloud('container', 'images', 'describe', args.image,
                    '--format=value(image_summary.digest)', timeout=120)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise RuntimeError('Registry did not return a valid digest')
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.image],
                                             text=True, timeout=30))[0]
    if f'{REPOSITORY}@{digest}' not in info.get('RepoDigests', []):
        raise RuntimeError('Registry digest differs from the image pushed by this build')
    Path(args.output).write_text(json.dumps({'tag': args.image, 'digest': digest}) + '\n')


if __name__ == '__main__':
    main()
