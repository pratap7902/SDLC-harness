FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /server

COPY requirements.txt /server/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /server/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8791
ENTRYPOINT ["/entrypoint.sh"]
