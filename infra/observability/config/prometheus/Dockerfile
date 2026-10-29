FROM prom/prometheus:v3.0.1

COPY --chmod=755 ./prometheus.yml /etc/prometheus/prometheus.yml

# requerido por metrics_generator de Tempo
CMD [ "--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.retention.time=30d", "--web.enable-remote-write-receiver" ]
