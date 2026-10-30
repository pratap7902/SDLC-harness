"""python -m runner <command>

  run        poll next_work forever (SIGTERM/SIGINT: stop polling, finish in-flight jobs)
  once       poll until there is nothing left to take, then exit (cron-friendly)
  harvest    run harvest-learnings once (schedule weekly)
  check      print what is missing from the configuration; exit 1 if anything is
  exec-job   (docker mode, inside the container) run one job file and write result.json"""

import asyncio
import json
import signal
import sys
from pathlib import Path

from runner import log as logmod
from runner.config import Settings
from runner.log import log


async def _main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    settings = Settings.from_env()
    logmod.setup(settings.log_level)
    if cmd == "check":
        problems = settings.problems()
        for p in problems:
            print(f"missing: {p}")
        from runner.skills import load_all

        try:
            print(f"skills: {', '.join(sorted(load_all(settings.skills_dir)))}")
        except ValueError as e:
            print(f"skills: {e}")
            return 1
        return 1 if problems else 0
    if cmd in ("run", "once", "harvest", "exec-job"):
        if not Settings.api_auth():
            log.error("no_api_auth", detail="set ANTHROPIC_API_KEY or CLAUDE_CODE_USE_BEDROCK / _VERTEX / _FOUNDRY / _ANTHROPIC_AWS; claude.ai login is never used")
            return 2
        from runner.agent import cli_info

        if cmd != "run":  # `run` logs it in runner_started
            log.info("claude_cli", auth=Settings.api_auth(), **cli_info(settings))
    if cmd == "exec-job":
        from runner.agent import run_skill
        from runner.skills import load_all

        job_path = Path(argv[2])
        job = json.loads(job_path.read_text())
        skill = load_all(settings.skills_dir)[job["skill"]]
        res = await run_skill(settings, skill, job["prompt"], Path(job["cwd"]), job.get("env") or {})
        (job_path.parent / "result.json").write_text(json.dumps(res.to_dict()))
        return 0 if res.ok else 2

    from runner.worker import Worker

    worker = Worker(settings)
    try:
        if cmd == "once":
            out = await worker.run_until_idle()
            print(json.dumps(out, indent=1, default=str))
            return 0
        if cmd == "harvest":
            print(json.dumps(await worker.harvest(), default=str))
            return 0
        if cmd == "run":
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)
            await worker.run_forever(stop)
            return 0
    finally:
        await worker.srs.aclose()
        if worker.github is not None:
            await worker.github.aclose()
    log.error("unknown_command", command=cmd)
    print(__doc__)
    return 2


def main() -> None:
    sys.exit(asyncio.run(_main(sys.argv)))


if __name__ == "__main__":
    main()
