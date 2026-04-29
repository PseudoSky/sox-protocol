FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the spec (needed for schema validation at startup)
COPY spec/ /app/spec/

# Copy the Python package
COPY packages/python/ /app/packages/python/

WORKDIR /app/packages/python

# Install the package with dependencies
RUN pip install --no-cache-dir -e .

# Default environment — overridden by docker-compose or the runner
ENV SOX_AGENT_ID=""
ENV SOX_BACKING_STORE="memory://"
ENV SOX_MCP_TRANSPORT="http"
ENV SOX_HTTP_HOST="0.0.0.0"
ENV SOX_HTTP_PORT="8000"

# Health check: poll the MCP HTTP endpoint
HEALTHCHECK --interval=2s --timeout=5s --start-period=10s --retries=15 \
    CMD curl -sf http://localhost:${SOX_HTTP_PORT}/health || \
        curl -sf -X POST http://localhost:${SOX_HTTP_PORT}/mcp \
            -H "Content-Type: application/json" \
            -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"healthcheck","version":"0.0.1"}}}' \
        || exit 1

EXPOSE 8000

CMD ["python", "-m", "sox_protocol.core.mcp_server"]
