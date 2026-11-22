"""Copy this standalone application onto a MicroPython T-Watch 2020 V1."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='e.g. /dev/ttyUSB0 or COM5')
    parser.add_argument('--backup', type=Path, help='Back up existing main.py before replacing it; fails if absent')
    args = parser.parse_args()
    command = [sys.executable, '-m', 'mpremote', 'connect', args.port]
    if args.backup:
        subprocess.run(command+['fs', 'cp', ':main.py', str(args.backup)], check=True)
    source = Path(__file__).resolve().parents[1] / 'twatch'
    # main.py last: don't launch a partially uploaded app on a normal reset.
    for name in ('config.py', 'model.py', 'display.py', 'main.py'):
        subprocess.run(command+['fs', 'cp', str(source/name), ':'+name], check=True)
    subprocess.run(command+['reset'], check=True)

if __name__ == '__main__':
    main()
