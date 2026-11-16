"""Build the offline, single-file presentation from its editable HTML and actual PNG captures.

Usage: python3 docs/build_presentation.py [--check]
The standalone output requires neither docs/ nor a web server. Only the live-demo link needs a network.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'docs/presentation.template.html'
ASSETS = ROOT / 'docs/assets/walkthrough'
OUTPUT = ROOT / '발표자료.html'
MARKER = '  <!-- EMBEDDED_CAPTURES -->'


class Presentation(HTMLParser):
    def __init__(self):
        super().__init__()
        self.slides = 0
        self.image_refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'section' and 'slide' in values.get('class', '').split():
            self.slides += 1
        if tag in ('img', 'script', 'link'):
            ref = values.get('href' if tag == 'link' else 'src')
            if ref:
                self.image_refs.append(ref)


def build() -> str:
    html = TEMPLATE.read_text(encoding='utf-8')
    manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    captures = [capture for capture in manifest['captures'] if not capture.get('retired', False)]
    images = {}
    for capture in captures:
        filename = capture['file']
        if Path(filename).name != filename or not filename.endswith('.png'):
            raise ValueError(f'Invalid capture filename: {filename}')
        data = (ASSETS / filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != capture['sha256']:
            raise ValueError(f'Capture checksum mismatch: {filename}')
        images[filename] = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    if len(images) != len(captures):
        raise ValueError('Duplicate capture filenames')
    if sum(bool(capture.get('selected')) for capture in captures) != manifest['selectedCount']:
        raise ValueError('Selected-capture count does not match the manifest')
    if html.count(MARKER) != 1:
        raise ValueError('Expected exactly one embedded-capture marker')
    parser = Presentation()
    parser.feed(html)
    html = html.replace('{{CAPTURE_COUNT}}', str(len(captures))).replace('{{SLIDE_COUNT}}', str(parser.slides))
    referenced_images = set()

    def inline_image(match):
        filename = match.group(1)
        referenced_images.add(filename)
        return 'src="' + images[filename] + '"'

    def inline_link(match):
        filename = match.group(1)
        if filename not in images:
            raise ValueError(f'Image link references a retired or absent capture: {filename}')
        return 'href="#" data-capture="' + filename + '"'

    html = re.sub(r'src="docs/assets/walkthrough/([^"/]+\.png)"', inline_image, html)
    html = re.sub(r'href="docs/assets/walkthrough/([^"/]+\.png)"', inline_link, html)
    selected = {capture['file'] for capture in captures if capture.get('selected')}
    if referenced_images != selected:
        raise ValueError('Slide images do not match the manifest selection')
    metadata_keys = ('file', 'role', 'caption', 'selected', 'notes', 'at', 'sha256')
    bundle = {
        'requestId': manifest['requestId'],
        'captures': [{key: capture[key] for key in metadata_keys if key in capture} for capture in captures],
        'images': images,
    }
    # Escape '<' so captions cannot terminate a script element; JSON is data, never executable code.
    payload = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = html.replace(MARKER, '  <script type="application/json" id="embedded-captures">' + payload + '</script>')
    html = html.replace('<!-- 빌드용 원본. python3 docs/build_presentation.py 실행으로 루트 발표자료.html 생성. -->',
                        '<!-- 이미지 내장형 단독 실행 파일. 편집 원본: docs/presentation.template.html; 재생성: python3 docs/build_presentation.py -->')
    check = Presentation()
    check.feed(html)
    if check.slides != parser.slides or any(not ref.startswith('data:image/') for ref in check.image_refs):
        raise ValueError('Output has external assets or a changed slide count')
    if '{{' in html or 'href="docs/' in html or 'src="docs/' in html:
        raise ValueError('Output has unresolved template values or local asset links')
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify the committed output without writing it')
    args = parser.parse_args()
    html = build()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding='utf-8') != html:
            parser.exit(1, '발표자료.html 재생성 필요\n')
        print('독립 실행 발표자료.html: 원본·선정·이미지 해시 일치')
    else:
        OUTPUT.write_text(html, encoding='utf-8')
        print(f'{OUTPUT.name}: {len(html.encode("utf-8")):,} bytes; 이미지 내장 완료')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
