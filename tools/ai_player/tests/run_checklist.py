"""Runs the whole checklist (tests/CHECKLIST.md): the offline tests first, then, with --live, Lyra in the game.

    python tests/run_checklist.py            # offline only (no server, no API)
    python tests/run_checklist.py --live     # plus the live checklist (server up, agent stopped)
    python tests/run_checklist.py --live --llm
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def main():
    args = sys.argv[1:]
    failed = []
    print("== Nivel 0: testes offline")
    for test in sorted(glob.glob(os.path.join(HERE, "offline", "test_*.py"))):
        run = subprocess.run([PY, test], capture_output=True, text=True, timeout=600)
        lines = (run.stdout + run.stderr).strip().splitlines()
        ok = run.returncode == 0 and lines and lines[-1].strip() == "PASS"
        print(f"[{'ok' if ok else 'FALHOU':6}] {os.path.basename(test)}")
        if not ok:
            failed.append(os.path.basename(test))
            print("\n".join("    " + l for l in lines[-15:]))
    if "--live" in args:
        print("\n== Niveis 1 a 5: Lyra no jogo")
        extra = ["--llm"] if "--llm" in args else []
        if subprocess.run([PY, os.path.join(HERE, "live.py"), *extra]).returncode != 0:
            failed.append("live")
    print("\nCHECKLIST " + ("OK" if not failed else f"COM FALHAS: {', '.join(failed)}"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
