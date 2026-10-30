# The SDLC harness runner. Build from the repository root (it needs skills/ too):
#   docker build -f runner/Dockerfile -t sdlc-harness-runner .
# The same image runs the poller (`python -m runner run`) and, in docker execution mode,
# each job (`python -m runner exec-job /job/job.json`). See docs/runner.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RUNNER_SKILLS_DIR=/app/skills \
    RUNNER_WORK_ROOT=/work

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 runner \
 && mkdir -p /work && chown runner /work

WORKDIR /app
COPY runner/requirements.txt /app/runner/requirements.txt
RUN pip install -r /app/runner/requirements.txt

COPY runner /app/runner
COPY skills /app/skills

USER runner
ENTRYPOINT ["python", "-m", "runner"]
CMD ["run"]
