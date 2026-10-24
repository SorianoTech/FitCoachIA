--
-- Publication audit and least-privilege writer role for approved exercises.
--

\connect fitcoach

CREATE TABLE IF NOT EXISTS public.exercise_publications (
    submission_id bigint PRIMARY KEY,
    exercise_id bigint NOT NULL UNIQUE REFERENCES public.exercises(id) ON DELETE RESTRICT,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

ALTER TABLE public.exercise_publications OWNER TO fitcoach;

-- The initial dump preserves source ids but its sequence was left at 1.
-- Move it after the corpus before accepting application inserts.
SELECT pg_catalog.setval(
    'public.exercises_id_seq',
    COALESCE((SELECT MAX(id) FROM public.exercises), 0) + 1,
    false
);

\set writer_password `echo "${VECTOR_DB_WRITER_PASSWORD:-fitcoach_writer_dev}"`

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fitcoach_writer') THEN
        CREATE ROLE fitcoach_writer LOGIN;
    END IF;
END
$$;

ALTER ROLE fitcoach_writer WITH PASSWORD :'writer_password';

GRANT CONNECT ON DATABASE fitcoach TO fitcoach_writer;
GRANT USAGE ON SCHEMA public TO fitcoach_writer;
GRANT USAGE, SELECT ON SEQUENCE public.exercises_id_seq TO fitcoach_writer;
GRANT SELECT (id) ON public.exercises TO fitcoach_writer;
GRANT INSERT (
    name, category, body_part, equipment, muscle_group, target,
    secondary_muscles, instructions_en, instructions_tr, created_at, metadata_vector
) ON public.exercises TO fitcoach_writer;
GRANT SELECT, INSERT ON public.exercise_publications TO fitcoach_writer;
