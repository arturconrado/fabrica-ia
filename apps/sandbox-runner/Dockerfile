FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==8.4.1

RUN useradd --uid 10001 --create-home sandbox
USER 10001:10001

WORKDIR /workspace
