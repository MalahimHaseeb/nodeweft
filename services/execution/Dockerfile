FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/execution/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY libs/common/common /app/common
COPY services/execution/app /app/app
RUN useradd --system --uid 10001 appuser && mkdir -p /data/files && chown appuser /data/files
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
