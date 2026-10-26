"""Build once, test, and smoke-check the Dockerfile's default CMD."""
import json
from pathlib import Path
import signal
import subprocess
import sys
import uuid

from smoke_http import check

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, capture=False, required=True):
    result = subprocess.run(['docker', *args], cwd=ROOT, check=required,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, interrupted)
    image = f'okinawago-check:{uuid.uuid4().hex}'
    containers = []
    server = None
    try:
        docker('build', '-t', image, '.')
        tests = docker('create', '-e', 'SECRET_KEY=ci-only-test-secret', image,
                       'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v', capture=True)
        containers.append(tests)
        docker('start', '-a', tests)
        status = json.loads(docker('inspect', tests, capture=True))[0]['State']['ExitCode']
        if status != 0:
            raise RuntimeError(f'unittest failed (exit {status})')
        server = docker('create', '-e', 'SECRET_KEY=ci-only-test-secret', '-e', 'PORT=8080',
                        '-p', '127.0.0.1::8080', image, capture=True)
        containers.append(server)
        docker('start', server)
        info = json.loads(docker('inspect', server, capture=True))[0]
        port = info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
        check(f'http://127.0.0.1:{port}')
        print('All checks passed.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        if server:
            docker('logs', server, required=False)
        return 1
    finally:
        for container in reversed(containers):
            docker('rm', '-f', container, required=False)
        docker('image', 'rm', image, required=False)


if __name__ == '__main__':
    sys.exit(main())
