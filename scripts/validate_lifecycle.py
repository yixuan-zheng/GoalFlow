"""Run all 38 existing GoalFlow contract cells in a fresh output directory."""
from pathlib import Path
import sys
import tempfile
from goalflow_world.store import ROOT


def main():
    sys.path.insert(0, str(ROOT/'experiments/work-lifecycle'))
    from scenarios import Case, SCENARIOS
    from supplemental import SUPPLEMENTAL, SQLITE_ONLY
    root = Path(tempfile.mkdtemp(prefix='goalflow-contract-'))
    count = 0
    for domain in ['coding', 'research']:
        for name, function in {**SCENARIOS, **SUPPLEMENTAL, **SQLITE_ONLY}.items():
            case = Case('goalflow_minimal', domain, name, root/domain/name)
            try:
                function(case)
                count += 1
            finally:
                case.trace.close()
    print(f'{count}/38 cells passed; evidence: {root}')

if __name__ == '__main__':
    main()
