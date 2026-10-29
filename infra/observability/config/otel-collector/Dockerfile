FROM otel/opentelemetry-collector-contrib:0.116.1

COPY --chmod=755 ./otel-collector.yml /etc/otel-collector/otel-collector.yml

CMD [ "--config=/etc/otel-collector/otel-collector.yml" ]
