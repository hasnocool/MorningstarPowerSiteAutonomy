FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
COPY config.example.toml ./config.toml
EXPOSE 8091
CMD ["powersite-autonomy", "--config", "config.toml", "serve"]
