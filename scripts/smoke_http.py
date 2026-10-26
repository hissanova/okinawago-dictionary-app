"""HTTP smoke checks, using only the Python standard library."""
import argparse
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import sys
import time
from urllib.error import URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.token = None
        self.links = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == 'csrf_token':
            self.token = attrs.get('value')
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])

    def handle_data(self, data):
        self.text.append(data)

    def require(self, text):
        if text not in ''.join(self.text):
            raise RuntimeError(f'Expected page content missing: {text!r}')


class Client:
    def __init__(self, base_url):
        self.base = base_url.rstrip('/') + '/'
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, path='', data=None, timeout=5):
        url = urljoin(self.base, path)
        if urlsplit(url).netloc != urlsplit(self.base).netloc:
            raise RuntimeError('Unexpected external URL')
        body = urlencode(data).encode() if data is not None else None
        with self.opener.open(Request(url, data=body), timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f'Unexpected HTTP status: {response.status}')
            return Page(response.read().decode('utf-8')), response.url


def check(base_url, startup_timeout=60):
    client = Client(base_url)
    deadline = time.monotonic() + startup_timeout
    while True:
        try:
            page, _ = client.request(timeout=min(5, max(0.1, deadline - time.monotonic())))
            break
        except (URLError, TimeoutError, OSError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Server not ready within {startup_timeout}s: {error}') from error
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    page.require('沖日辞典・日沖辞典')
    for dictionary, word, expected, detail_heading, definition_text in [
        ('oki2yamato', 'あー', 'アー', 'アー', '物事に深く感じた時発する声'),
        ('yamato2oki', 'ああ', 'ああ', 'ああ', 'アキヨ'),
        # Bundled entry: search index アーイン, detail heading あーいん, meaning 〈合う〉.
        ('katsuyou_jiten', 'あーいん', 'アーイン', 'あーいん', '〈合う〉'),
    ]:
        page, _ = client.request()
        if not page.token:
            raise RuntimeError('Missing CSRF token')
        result, url = client.request(data={
            'csrf_token': page.token, 'word': word,
            'search_type': 'startswith', 'dict_type': dictionary,
        })
        if '/search-results/' not in urlsplit(url).path:
            raise RuntimeError('Search did not reach results (form validation failed)')
        result.require('件の検索結果が見つかりました')
        result.require(expected)
        target = f'/definition/{dictionary}/{quote(expected)}'
        if target not in result.links:
            raise RuntimeError(f'Expected result/detail link missing: {target}')
        detail, _ = client.request(target)
        detail.require(detail_heading)
        detail.require(definition_text)
        print(f'HTTP OK: {dictionary} search and definition', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--startup-timeout', type=float, default=60)
    args = parser.parse_args()
    if args.startup_timeout <= 0 or urlsplit(args.base_url).scheme not in ('http', 'https'):
        parser.error('Use an HTTP(S) URL and a positive startup timeout')
    try:
        check(args.base_url, args.startup_timeout)
    except Exception as error:
        print(f'HTTP check failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
