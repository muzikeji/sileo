#!/usr/bin/env python3
"""Regenerate Packages, Packages.{gz,bz2,xz,zst} and Release for Sileo repo."""
import gzip
import bz2
import lzma
import zstandard as zstd
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROOTLESS = ROOT / 'rootless'
ROOTHIDE = ROOT / 'roothide'
ICON_URL = 'https://muzikeji.github.io/sileo/icons'
DEPICTION_URL = 'https://muzikeji.github.io/sileo/depictions'


def parse_control(deb_path):
    """Run dpkg-deb -f to extract control fields."""
    out = subprocess.run(
        ['dpkg-deb', '-f', str(deb_path), 'Package', 'Version', 'Architecture',
         'Maintainer', 'Name', 'Description', 'Depiction', 'SileoDepiction',
         'Icon', 'Tag', 'Depends', 'Conflicts', 'Replaces', 'Section'],
        capture_output=True, text=True, check=True,
    ).stdout
    fields = {}
    for line in out.splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()
    return fields


def control_block(deb_path, fields, size, md5, sha256, filename):
    """Emit one Packages stanza."""
    parts = [f'Package: {fields["Package"]}',
             f'Version: {fields["Version"]}',
             f'Architecture: {fields["Architecture"]}',
             f'Maintainer: {fields["Maintainer"]}',
             f'Filename: {filename}',
             f'Size: {size}',
             f'MD5sum: {md5}',
             f'SHA256: {sha256}',
             f'Name: {fields["Name"]}',
             f'Description: {fields["Description"]}']
    if 'Tag' in fields and fields['Tag']:
        parts.append(f'Tag: {fields["Tag"]}')
    if 'Depends' in fields and fields['Depends']:
        parts.append(f'Depends: {fields["Depends"]}')
    if 'Conflicts' in fields and fields['Conflicts']:
        parts.append(f'Conflicts: {fields["Conflicts"]}')
    if 'Replaces' in fields and fields['Replaces']:
        parts.append(f'Replaces: {fields["Replaces"]}')
    if 'Section' in fields and fields['Section']:
        parts.append(f'Section: {fields["Section"]}')
    # icon + depiction: derive from package id
    pkg = fields['Package']
    # SileoDepiction：Sileo 优先用它显示原生 JSON 包简介；包内已声明则用包内地址
    if 'SileoDepiction' in fields and fields['SileoDepiction']:
        parts.append(f'SileoDepiction: {fields["SileoDepiction"]}')
    else:
        parts.append(f'SileoDepiction: {DEPICTION_URL}/{pkg}.json')
    parts.append(f'Depiction: {DEPICTION_URL}/{pkg}.json')
    # Icon name: special-case the DuoStatusBar icon name (does NOT follow
    # the default com.duo.* → strip prefix convention). 其余包按包内 control
    # 声明的 Icon（若有）原样输出，避免派生规则拼出 404 路径。
    icon_field = fields.get('Icon', '').strip()
    if icon_field:
        parts.append(f'Icon: {icon_field}')
    else:
        if pkg == 'com.duo.statusbar':
            icon_name = 'duostatusbar.png'
        elif pkg.startswith('com.muzi.'):
            icon_name = pkg.replace('com.muzi.', '') + '.png'
        else:
            icon_name = pkg.replace('com.duo.', '') + '.png'
        parts.append(f'Icon: {ICON_URL}/{icon_name}')
    return '\n'.join(parts) + '\n'


def scan_dir(d):
    """Return sorted list of deb paths."""
    return sorted(d.glob('*.deb'))


def main():
    debs = []
    for d in [ROOTLESS, ROOTHIDE]:
        for p in scan_dir(d):
            fields = parse_control(p)
            data = p.read_bytes()
            size = len(data)
            md5 = hashlib.md5(data).hexdigest()
            sha256 = hashlib.sha256(data).hexdigest()
            # filename relative to repo root (so URLs are depth-correct on GH Pages)
            filename = p.name
            # Adjust Filename to include subdir
            rel = f'{"rootless" if d == ROOTLESS else "roothide"}/{filename}'
            debs.append((d, p, fields, size, md5, sha256, rel))

    # Sort by Package + Version
    debs.sort(key=lambda x: (x[2]['Package'], x[2]['Version']))

    blocks = []
    for d, p, fields, size, md5, sha256, rel in debs:
        blocks.append(control_block(p, fields, size, md5, sha256, rel))

    body = '\n'.join(blocks) + '\n'

    (ROOT / 'Packages').write_text(body)

    # Compress
    (ROOT / 'Packages.gz').write_bytes(gzip.compress(body.encode()))
    (ROOT / 'Packages.bz2').write_bytes(bz2.compress(body.encode()))
    (ROOT / 'Packages.xz').write_bytes(lzma.compress(body.encode()))
    cctx = zstd.ZstdCompressor()
    (ROOT / 'Packages.zst').write_bytes(cctx.compress(body.encode()))

    # Generate Release
    sizes = {'Packages': len(body.encode())}
    sha256s = {'Packages': hashlib.sha256(body.encode()).hexdigest()}
    for name in ['Packages.gz', 'Packages.bz2', 'Packages.xz', 'Packages.zst']:
        path = ROOT / name
        data = path.read_bytes()
        sizes[name] = len(data)
        sha256s[name] = hashlib.sha256(data).hexdigest()

    release = ['Origin: Muzi Sileo Repo',
               'Label: Muzi',
               'Suite: stable',
               'Version: 1.0',
               'Codename: muzi',
               'Date: ' + subprocess.run(['date', '-u', '+%a, %d %b %Y %H:%M:%S +0000'],
                                         capture_output=True, text=True).stdout.strip(),
               'Architectures: iphoneos-arm64 iphoneos-arm64e',
               'Components: main',
               'Description: MUtool 多功能工具集越狱源。灵动岛电池胶囊、悬浮信息药丸、状态栏图标分色与 VPN 变色、充电限制与智能温度停充、温控调校、通话自动录音、录屏增强、定时任务、自动禁用 SIM、三合一状态栏、电池健康等。支持 rootless / roothide，iOS 15-17。',
               '']
    release.append('MD5Sum:')
    for name in ['Packages', 'Packages.gz', 'Packages.bz2', 'Packages.xz', 'Packages.zst']:
        md5 = hashlib.md5((ROOT / name).read_bytes()).hexdigest()
        release.append(f' {md5} {sizes[name]} {name}')
    release.append('SHA256:')
    for name in ['Packages', 'Packages.gz', 'Packages.bz2', 'Packages.xz', 'Packages.zst']:
        release.append(f' {sha256s[name]} {sizes[name]} {name}')

    (ROOT / 'Release').write_text('\n'.join(release) + '\n')

    print(f'Wrote Packages with {len(debs)} entries')
    print(f'Wrote Release')


if __name__ == '__main__':
    main()
