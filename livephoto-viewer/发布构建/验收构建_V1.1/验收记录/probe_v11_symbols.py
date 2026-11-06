import sys, marshal, re
from PyInstaller.archive.readers import CArchiveReader

path = sys.argv[1]
r = CArchiveReader(path)
data = r.extract('LivePhoto_Backup')
code = marshal.loads(data)
names = set()
def walk(c):
    for const in c.co_consts:
        if isinstance(const, str):
            names.add(const)
        elif hasattr(const, 'co_consts'):
            walk(const)
    names.update(c.co_names)
walk(code)
markers = ['run_preview', 'scan_groups', 'build_preview_html', 'to_file_url',
           'cleanup_stale_preview_dirs', '_is_our_preview_dir',
           'PREVIEW_MARKER_TEXT', 'livephoto_preview_',
           '只读预览扫描', '--preview', '预览已生成', '统计: 扫描']
for m in markers:
    print(('FOUND    ' if m in names else 'NOTFOUND ') + m)
print('---')
print('script_bytes_uncompressed =', len(data))
print('co_names_count =', len(code.co_names))
