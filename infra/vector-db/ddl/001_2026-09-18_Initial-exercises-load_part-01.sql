--
-- 001_2026-09-18_Initial-exercises-load_part-01.sql
-- Parte 1 de 8 de 001_2026-09-18_Initial-exercises-load.sql (troceado para respetar el limite de 100 MB
-- por fichero de GitHub). Las partes se aplican en orden alfabetico,
-- que es el que usa docker-entrypoint-initdb.d.
--

--
-- PostgreSQL database cluster dump
--

-- Started on 2026-09-18 09:02:20 UTC


SET default_transaction_read_only = off;

--
-- User Configurations
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

\connect fitcoach

--
-- TOC entry 2 (class 3079 OID 16385)
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- TOC entry 3698 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner:
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_table_access_method = heap;

--
-- TOC entry 223 (class 1259 OID 16725)
-- Name: exercise_media; Type: TABLE; Schema: public; Owner: fitcoach
--

CREATE TABLE public.exercise_media (
    id integer NOT NULL,
    exercise_id bigint NOT NULL,
    image_path text,
    gif_path text,
    image_data bytea,
    gif_data bytea
);


ALTER TABLE public.exercise_media OWNER TO fitcoach;

--
-- TOC entry 222 (class 1259 OID 16724)
-- Name: exercise_media_id_seq; Type: SEQUENCE; Schema: public; Owner: fitcoach
--

CREATE SEQUENCE public.exercise_media_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.exercise_media_id_seq OWNER TO fitcoach;

--
-- TOC entry 3699 (class 0 OID 0)
-- Dependencies: 222
-- Name: exercise_media_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: fitcoach
--

ALTER SEQUENCE public.exercise_media_id_seq OWNED BY public.exercise_media.id;


--
-- TOC entry 221 (class 1259 OID 16714)
-- Name: exercises; Type: TABLE; Schema: public; Owner: fitcoach
--

CREATE TABLE public.exercises (
    id bigint NOT NULL,
    name text NOT NULL,
    category text,
    body_part text,
    equipment text,
    muscle_group text,
    target text,
    secondary_muscles text[],
    instructions_en text,
    instructions_tr text,
    created_at timestamp with time zone,
    metadata_vector public.vector(384)
);


ALTER TABLE public.exercises OWNER TO fitcoach;

--
-- TOC entry 220 (class 1259 OID 16713)
-- Name: exercises_id_seq; Type: SEQUENCE; Schema: public; Owner: fitcoach
--

CREATE SEQUENCE public.exercises_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.exercises_id_seq OWNER TO fitcoach;

--
-- TOC entry 3700 (class 0 OID 0)
-- Dependencies: 220
-- Name: exercises_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: fitcoach
--

ALTER SEQUENCE public.exercises_id_seq OWNED BY public.exercises.id;


--
-- TOC entry 3533 (class 2604 OID 16728)
-- Name: exercise_media id; Type: DEFAULT; Schema: public; Owner: fitcoach
--

ALTER TABLE ONLY public.exercise_media ALTER COLUMN id SET DEFAULT nextval('public.exercise_media_id_seq'::regclass);


--
-- TOC entry 3532 (class 2604 OID 16717)
-- Name: exercises id; Type: DEFAULT; Schema: public; Owner: fitcoach
--

ALTER TABLE ONLY public.exercises ALTER COLUMN id SET DEFAULT nextval('public.exercises_id_seq'::regclass);


--
-- TOC entry 3691 (class 0 OID 16725)
-- Dependencies: 223
-- Data for Name: exercise_media; Type: TABLE DATA; Schema: public; Owner: fitcoach
--
