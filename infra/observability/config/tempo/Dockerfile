FROM grafana/tempo:2.6.1

COPY --chmod=755 ./tempo.yml /etc/tempo/tempo.yml

CMD [ "-config.file=/etc/tempo/tempo.yml" ]
