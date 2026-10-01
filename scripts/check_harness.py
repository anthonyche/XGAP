"""Check the distributable source tree; do not inspect local experiment outputs."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BANNED_PREFIXES = (
    'docs/report/', 'docs/decisions/', 'prompts/sprints/', 'experiments/artifacts/',
    'experiments/handoffs/', 'experiments/replays/', 'experiments/calibration/',
    'runs/', 'results/', 'outputs/', 'node_modules/',
    'datasets/grailqa_audit/', 'datasets/grailqa_audit_v2/', 'datasets/kqapro_audit/',
    'datasets/grailqa_reachability_v2/', 'datasets/grailqa_m13d_reachability_baseline/',
)
BANNED_SUFFIXES = ('.zip', '.tar', '.tar.gz', '.log', '.out', '.pyc', '.pem', '.pdf')


def main():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = [p for p in tracked if p and (ROOT / p).is_file()]
    errors = []
    for p in paths:
        name = Path(p).name
        if (p.startswith(BANNED_PREFIXES) or '_history_' in name or '/.openai/' in p
                or p.endswith(BANNED_SUFFIXES) or (name.startswith('.env') and not name.endswith('.example'))
                or name in {'goal.md', 'status.md', 'roadmap.md', 'id_rsa', 'id_ed25519'}):
            errors.append('Non-distributable file: ' + p)
    for p in [ROOT/'README.md', *sorted((ROOT/'docs').glob('*.md'))]:
        if not p.is_file():
            errors.append('Missing documentation: ' + str(p.relative_to(ROOT)))
            continue
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            target = target.split('#', 1)[0]
            if not target or '://' in target or target.startswith('mailto:'):
                continue
            if not (p.parent / target).exists():
                errors.append(f'Broken local link in {p.relative_to(ROOT)}: {target}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Repository hygiene passed ({len(paths)} tracked files).')


if __name__ == '__main__':
    main()
