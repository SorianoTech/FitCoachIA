--
-- 002_2026-09-21_readonly-role.sql
-- Rol de solo lectura para la aplicacion.
--
-- La app solo consulta ejercicios: nunca escribe en esta base de datos. Usar el
-- rol `fitcoach` (SUPERUSER, ver el volcado inicial) desde el webhook seria dar
-- permisos de escritura a un proceso que no los necesita.
--
-- Los ficheros de docker-entrypoint-initdb.d se aplican en orden alfabetico, asi
-- que este corre despues de las 8 partes de la carga inicial.
--
-- La contrasena se toma de VECTOR_DB_RO_PASSWORD; si no esta definida, se usa un
-- valor de desarrollo. Definela SIEMPRE en pre/pro.
--

\connect fitcoach

\set ro_password `echo "${VECTOR_DB_RO_PASSWORD:-fitcoach_ro_dev}"`

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fitcoach_ro') THEN
        CREATE ROLE fitcoach_ro LOGIN;
    END IF;
END
$$;

ALTER ROLE fitcoach_ro WITH PASSWORD :'ro_password';

GRANT CONNECT ON DATABASE fitcoach TO fitcoach_ro;
GRANT USAGE ON SCHEMA public TO fitcoach_ro;
GRANT SELECT ON public.exercises TO fitcoach_ro;
GRANT SELECT ON public.exercise_media TO fitcoach_ro;

-- Cualquier tabla futura del esquema nace tambien como solo lectura para este rol.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO fitcoach_ro;
