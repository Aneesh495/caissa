"""Render editable execution-contract diagrams with Graphviz."""
import argparse,subprocess,xml.etree.ElementTree as ET
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--png',action='store_true');a=ap.parse_args();root=Path('docs/diagrams');rows=[]
    for source in sorted(root.glob('*.dot')):
        target=source.with_suffix('.svg');subprocess.run(['dot','-Tsvg',str(source),'-o',str(target)],check=True,timeout=20);ET.parse(target)
        if a.png:subprocess.run(['dot','-Tpng',str(source),'-o',str(Path('runs')/source.with_suffix('.png').name)],check=True,timeout=20)
        rows.append(source.stem)
    if len(rows)<12:raise ValueError('required execution views missing')
    print('Rendered and parsed '+str(len(rows))+' distinct contract diagrams')
if __name__=='__main__':main()
