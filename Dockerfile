FROM python:3.12-alpine
ENV TZ="Asia/Shanghai"

WORKDIR /tmp

RUN apk add --no-cache git \
    && git config --global --add safe.directory "*" \
    && git clone https://github.com/brestain/bili_fansmedal_feeder.git /app/bili_fansmedal_feeder \
    && pip install --no-cache-dir -r /app/bili_fansmedal_feeder/requirements.txt \
    && rm -rf /tmp/*

WORKDIR /app/bili_fansmedal_feeder

ENTRYPOINT ["/bin/sh","/app/bili_fansmedal_feeder/entrypoint.sh"]

