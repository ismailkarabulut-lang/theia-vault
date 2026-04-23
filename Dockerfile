FROM python:3.13-slim

RUN useradd -m -s /bin/bash sandbox

WORKDIR /sandbox

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gatekeeper.py .

USER sandbox

CMD ["python3", "-c", "from gatekeeper import SandboxExecutor; import sys; ok, out = SandboxExecutor().run(' '.join(sys.argv[1:])); print(out); sys.exit(0 if ok else 1)"]
