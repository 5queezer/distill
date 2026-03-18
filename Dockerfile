FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv sync --extra postgres
CMD ["uv", "run", "python", "-m", "distill_mcp"]
