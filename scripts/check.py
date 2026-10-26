"""Build once, test, and smoke-check the Dockerfile's default CMD."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, capture=False, required=True, timeout=120):
    result = subprocess.run(['docker', *args], cwd=ROOT, check=required,
                            text=True, stdout=subprocess.PIPE if capture else None,
                            timeout=timeout)
    return result.stdout.strip() if capture else None


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', help='Check an already-built image; keep it afterwards')
    args = parser.parse_args()
    image = args.image or f'okinawago-check:{uuid.uuid4().hex}'
    containers = []
    server = None
    try:
        if not args.image:
            docker('build', '-t', image, '.', timeout=600)
        tests = docker('create', '-e', 'SECRET_KEY=ci-only-test-secret', image,
                       'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v', capture=True)
        containers.append(tests)
        docker('start', '-a', tests)
        status = json.loads(docker('inspect', tests, capture=True))[0]['State']['ExitCode']
        if status != 0:
            raise RuntimeError(f'unittest failed (exit {status})')
        server = docker('create', '-e', 'SECRET_KEY=ci-only-test-secret', '-e', 'PORT=8080',
                        image, capture=True)
        containers.append(server)
        docker('start', server)
        # Both containers run on the Docker daemon, even when the caller runs in
        # a Cloud Build step container. No host port or caller localhost is used.
        client = docker('create', '--network', f'container:{server}', image,
                        'python', 'scripts/smoke_http.py', 'http://127.0.0.1:8080',
                        capture=True)
        containers.append(client)
        docker('start', '-a', client)
        status = json.loads(docker('inspect', client, capture=True))[0]['State']['ExitCode']
        if status != 0:
            raise RuntimeError(f'HTTP checks failed (exit {status})')
        print('All checks passed.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        if server:
            try:
                docker('logs', server, required=False)
            except Exception as log_error:
                print(f'Container logs unavailable: {log_error}', file=sys.stderr)
        return 1
    finally:
        for container in reversed(containers):
            try:
                docker('rm', '-f', container, required=False)
            except Exception as error:
                print(f'Container cleanup failed: {error}', file=sys.stderr)
        if not args.image:
            try:
                docker('image', 'rm', image, required=False)
            except Exception as error:
                print(f'Image cleanup failed: {error}', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
