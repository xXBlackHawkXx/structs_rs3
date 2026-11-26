"""Refresh change history and build the viewer at the same dump commit."""
import argparse
from pathlib import Path
import subprocess
import sys

from builder.history import write_json
from .refresh import DEFAULT_STATE, ROOT, refresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='master')
    parser.add_argument('--compress-json',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT / 'dist')
    args = parser.parse_args()
    state = refresh(args.ref,force=True)
    write_json(DEFAULT_STATE,state)
    command = [sys.executable,'-m','builder.build','--ref',state['revision'],'--output',str(args.output),
               '--pipeline-state',str(DEFAULT_STATE)]
    if args.compress_json:
        command.append('--compress-json')
    subprocess.run(command,cwd=ROOT,check=True)


if __name__ == '__main__':
    main()
