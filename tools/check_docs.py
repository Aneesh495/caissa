"""Check source-linked local documentation and public prose constraints."""
import re,subprocess
from pathlib import Path
paths=subprocess.check_output(['git','ls-files','-z']).decode().split('\0');errors=[];checked=0
for name in paths:
    p=Path(name)
    if p.suffix!='.md' or not p.exists():continue
    text=p.read_text();checked+=1
    if '\u2014' in text:errors.append(f'{p}: forbidden dash')
    for target in re.findall(r'\]\(([^)]+)\)',text):
        if target.startswith(('https://','http://','#')):continue
        destination=target.split('#',1)[0]
        if destination and not (p.parent/destination).exists():errors.append(f'{p}: missing local link {destination}')
if errors:raise SystemExit('\n'.join(errors))
print(f'{checked} tracked Markdown files checked')
