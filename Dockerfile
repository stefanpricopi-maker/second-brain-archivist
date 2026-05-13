# Build: docker build -t second-brain-archivist .
# Run:  docker run --rm -p 8090:8090 -e LLM_MODE=disabled \
#          -v "$(pwd)/data/vectorstore:/app/data/vectorstore" \
#          -v "$(pwd)/data/library:/app/data/library" \
#          second-brain-archivist

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ghostscript qpdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY mcp_server ./mcp_server
COPY knowledge ./knowledge

RUN mkdir -p data/vectorstore data/library \
    && useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app

USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
