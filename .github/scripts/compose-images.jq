# Imagenes construibles de `docker compose config --no-interpolate --format json`.
# Argumentos: $root (raiz del checkout) y $version (version de la release, para la app).
[.services | to_entries[] | select(.value.build)
 | (.value.build.context | if . == $root then "." else "./" + ltrimstr($root + "/") end) as $ctx
 | {service: .key,
    image: (.value.image | sub("\\$\\{VERSION:-latest\\}$"; $version)),
    context: $ctx,
    file: ($ctx + "/" + .value.build.dockerfile)}]
