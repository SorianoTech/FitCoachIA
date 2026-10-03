--
-- 001_2026-09-18_Initial-exercises-load_part-08.sql
-- Parte 8 de 8 de 001_2026-09-18_Initial-exercises-load.sql (troceado para respetar el limite de 100 MB
-- por fichero de GitHub). Las partes se aplican en orden alfabetico,
-- que es el que usa docker-entrypoint-initdb.d.
--

\connect fitcoach

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;



--
-- TOC entry 3701 (class 0 OID 0)
-- Dependencies: 222
-- Name: exercise_media_id_seq; Type: SEQUENCE SET; Schema: public; Owner: fitcoach
--

SELECT pg_catalog.setval('public.exercise_media_id_seq', 1324, true);


--
-- TOC entry 3702 (class 0 OID 0)
-- Dependencies: 220
-- Name: exercises_id_seq; Type: SEQUENCE SET; Schema: public; Owner: fitcoach
--

SELECT pg_catalog.setval('public.exercises_id_seq', 1, false);


--
-- TOC entry 3539 (class 2606 OID 16734)
-- Name: exercise_media exercise_media_pkey; Type: CONSTRAINT; Schema: public; Owner: fitcoach
--

ALTER TABLE ONLY public.exercise_media
    ADD CONSTRAINT exercise_media_pkey PRIMARY KEY (id);


--
-- TOC entry 3536 (class 2606 OID 16723)
-- Name: exercises exercises_pkey; Type: CONSTRAINT; Schema: public; Owner: fitcoach
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT exercises_pkey PRIMARY KEY (id);


--
-- TOC entry 3537 (class 1259 OID 16741)
-- Name: exercise_media_exercise_id_idx; Type: INDEX; Schema: public; Owner: fitcoach
--

CREATE INDEX exercise_media_exercise_id_idx ON public.exercise_media USING btree (exercise_id);


--
-- TOC entry 3534 (class 1259 OID 16740)
-- Name: exercises_metadata_vec_idx; Type: INDEX; Schema: public; Owner: fitcoach
--

CREATE INDEX exercises_metadata_vec_idx ON public.exercises USING hnsw (metadata_vector public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- TOC entry 3540 (class 2606 OID 16735)
-- Name: exercise_media exercise_media_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: fitcoach
--

ALTER TABLE ONLY public.exercise_media
    ADD CONSTRAINT exercise_media_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id) ON DELETE CASCADE;


-- Completed on 2026-09-18 09:02:21 UTC

--
-- PostgreSQL database dump complete
--


--
-- Database "postgres" dump
--

\connect postgres

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (Debian 18.6-1.pgdg13+2)
-- Dumped by pg_dump version 18.4

-- Started on 2026-09-18 09:02:21 UTC

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- Completed on 2026-09-18 09:02:21 UTC

--
-- PostgreSQL database dump complete
--


-- Completed on 2026-09-18 09:02:21 UTC

--
-- PostgreSQL database cluster dump complete
--
