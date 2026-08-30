"""Сторож монтажного стола: забирает правки с сайта и пересобирает ролик.

Стол живёт на сервере с сайтом и ничего не запускает сам — иначе сайту понадобились
бы ключи и доступ к фабрике. Забирает задания эта сторожевая программа: раз в две
минуты по крону, с замком от наложения прогонов и с пометкой обработанного на сервере,
чтобы одно и то же задание не собралось дважды.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
REMOTE = "crm"
REMOTE_DIR = "/opt/montage-desk/edits"
LOCK = Path("/tmp/montage-desk-watch.lock")
LOG = ROOT / "desk" / "watch.log"
TG = Path.home() / "scripts" / "tg.py"


def log(message: str) -> None:
    line = f"{time.strftime('%F %T')} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, **kwargs)


def telegram(text: str, file_path: Path | None = None, caption: str | None = None) -> None:
    if not TG.is_file():
        log("tg.py не найден — сообщение не ушло")
        return
    command = ["python3", str(TG), "--no-ito"]
    if file_path is not None:
        command += ["-f", str(file_path)]
        if caption:
            command += ["-c", caption]
    else:
        command += ["--stdin"]
    result = run(command, input=None if file_path else text)
    if result.returncode != 0:
        log(f"telegram failed: {result.stderr[-200:]}")


def project_for(desk_id: str) -> Path | None:
    """Проект ищем по его же выгрузке: id стола записан внутри desk.json."""
    for candidate in sorted(PROJECTS.glob("*/03_phase1/desk.json")):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if str(payload.get("project_id")) == desk_id:
            return candidate.parents[1]
    return None


def pending_jobs() -> list[str]:
    result = run(["ssh", REMOTE, f"ls -1 {REMOTE_DIR}/*.submit.json 2>/dev/null"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def handle(remote_path: str) -> None:
    name = Path(remote_path).name
    local = Path("/tmp") / name
    if run(["scp", "-q", f"{REMOTE}:{remote_path}", str(local)]).returncode != 0:
        log(f"не забрал {name}")
        return
    submit = json.loads(local.read_text(encoding="utf-8"))
    desk_id = str(submit.get("desk_id") or "")
    project = project_for(desk_id)
    if project is None:
        log(f"{name}: проект для {desk_id} не найден")
        telegram(f"Правки со стола пришли, но проект `{desk_id}` не найден — разберусь руками.")
        run(["ssh", REMOTE, f"mv {remote_path} {remote_path}.orphan"])
        return

    log(f"{name}: проект {project.name}, вычеркнуто слов {len(submit.get('cut_words') or [])}")
    applied = run([str(VENV_PYTHON), str(ROOT / "desk" / "apply_edits.py"), str(project), str(local)])
    if applied.returncode != 0:
        log(f"{name}: правки не применились: {applied.stderr[-300:]}")
        telegram("Правки со стола не применились — смотрю сам.")
        return
    log(applied.stdout.strip())

    note = str(submit.get("note") or "").strip()
    telegram(
        "**Правки со стола приняты**\n\n"
        f"{applied.stdout.strip()}\n\n"
        + (f"Ваше пожелание: «{note}»\n\n" if note else "")
        + "Собираю новый вариант, пришлю файлом."
    )

    env = dict(os.environ)
    approve = run([str(VENV_PYTHON), str(ROOT / "pipeline" / "studio.py"),
                   "approve", str(project), "gate1", "--reviewer", "desk"], cwd=ROOT, env=env)
    if approve.returncode != 0 and "cannot" not in approve.stderr.lower():
        log(f"{name}: гейт не принял: {approve.stderr[-300:]}")
    resume = run([str(VENV_PYTHON), str(ROOT / "pipeline" / "studio.py"),
                  "resume", str(project)], cwd=ROOT, env=env)
    log(f"{name}: сборка завершилась кодом {resume.returncode}")

    review = project / "04_phase2" / "segments" / "01" / "review.mp4"
    if review.is_file():
        verdicts = []
        for kind in ("verification.json", "qc.json"):
            path = review.parent / kind
            if path.is_file():
                try:
                    verdicts.append(f"{kind.split('.')[0]}: {json.loads(path.read_text(encoding='utf-8'))['verdict']}")
                except (ValueError, KeyError, OSError):
                    pass
        telegram("", file_path=review,
                 caption="Новый вариант по вашим правкам. " + ("; ".join(verdicts) if verdicts else ""))
    else:
        telegram("Сборка не дала файла — разбираюсь.")

    run(["ssh", REMOTE, f"mv {remote_path} {remote_path}.done"])
    local.unlink(missing_ok=True)


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # Замок: сборка идёт минутами, а крон приходит каждые две — без него прогоны
    # наложатся друг на друга и подерутся за один и тот же проект.
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - LOCK.stat().st_mtime
        if age < 3600:
            return 0
        log("замок протух, снимаю")
        LOCK.unlink(missing_ok=True)
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        for job in pending_jobs():
            handle(job)
    finally:
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
