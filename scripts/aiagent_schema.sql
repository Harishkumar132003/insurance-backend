--
-- PostgreSQL database dump
--

\restrict dUlmQaJkMSt2dGTXZS8umscbjUZz7FdNWKyagZbW3tnnmao9Z3wW7I8OyVdf3kZ

-- Dumped from database version 15.17 (Debian 15.17-1.pgdg13+1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: dblink; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA public;


--
-- Name: EXTENSION dblink; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION dblink IS 'connect to other PostgreSQL databases from within a database';


--
-- Name: fill_settlement_item_denorm(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fill_settlement_item_denorm() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    SELECT b.hospital_id, b.settlement_date
      INTO NEW.hospital_id, NEW.settlement_date
      FROM public.settlement_batch b
     WHERE b.id = NEW.batch_id;

    IF NEW.hospitalization_id IS NOT NULL THEN
        SELECT h.uhid
          INTO NEW.uhid
          FROM public.hospitalization h
         WHERE h.id = NEW.hospitalization_id;
    ELSE
        NEW.uhid := NULL;
    END IF;

    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: claim_case_emails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claim_case_emails (
    id bigint NOT NULL,
    direction character varying NOT NULL,
    from_email character varying NOT NULL,
    to_email character varying NOT NULL,
    subject character varying,
    body text,
    message_id character varying,
    thread_id character varying,
    email_date timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    email_type character varying,
    claim_case_id uuid NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    ai_suggested_status character varying,
    ai_suggested_amount numeric(12,2),
    ai_suggested_claim_number character varying,
    ai_summary text,
    ai_query_details text,
    ai_documents_requested text,
    validation_status character varying DEFAULT 'PENDING'::character varying NOT NULL,
    validated_at timestamp with time zone,
    validated_by uuid,
    provider_read boolean DEFAULT true NOT NULL,
    ai_documents_list jsonb,
    form_values jsonb,
    ai_approved_breakdown jsonb,
    ai_denial_reason text
);


--
-- Name: claim_case_emails_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.claim_case_emails_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: claim_case_emails_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.claim_case_emails_id_seq OWNED BY public.claim_case_emails.id;


--
-- Name: claim_status_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claim_status_tracking (
    id bigint NOT NULL,
    hospitalization_id uuid NOT NULL,
    uhid character varying,
    claim_number character varying,
    email_id bigint,
    from_status character varying,
    to_status character varying NOT NULL,
    turn_around_time interval,
    turn_around_time_text character varying,
    document_link jsonb,
    remark text,
    created_at timestamp with time zone DEFAULT now(),
    hospital_id uuid
);


--
-- Name: claim_status_tracking_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.claim_status_tracking_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: claim_status_tracking_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.claim_status_tracking_id_seq OWNED BY public.claim_status_tracking.id;


--
-- Name: claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claims (
    id bigint NOT NULL,
    claimed_amount numeric(12,2) NOT NULL,
    approved_amount numeric(12,2),
    status character varying NOT NULL,
    submitted_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    hospitalization_id uuid NOT NULL,
    uhid character varying,
    claim_number character varying,
    hospital_id uuid
);


--
-- Name: claims_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.claims_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: claims_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.claims_id_seq OWNED BY public.claims.id;


--
-- Name: hospitalization; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hospitalization (
    hospital_id uuid,
    policy_provider_id uuid NOT NULL,
    case_status character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    uhid character varying NOT NULL,
    claim_number character varying,
    current_stage character varying NOT NULL,
    preauth_outcome character varying,
    thread_id character varying,
    approved_amount numeric(12,2),
    id uuid NOT NULL
);


--
-- Name: hospitals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hospitals (
    id uuid NOT NULL,
    name character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    address character varying,
    rohini_id character varying,
    email character varying,
    app_password character varying
);


--
-- Name: policy_provider_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_provider_configs (
    id uuid NOT NULL,
    name character varying NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    provider_id character varying NOT NULL,
    email character varying,
    tpa_name character varying,
    tpa_toll_free_phone character varying,
    tpa_toll_free_fax character varying,
    is_onboarded boolean DEFAULT false NOT NULL
);


--
-- Name: settlement_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settlement_item (
    id bigint NOT NULL,
    batch_id uuid NOT NULL,
    claim_number character varying,
    settled_amount numeric(14,2),
    claim_raised_amount numeric(14,2),
    disallowance numeric(14,2),
    disallowance_reason character varying,
    hospitalization_id uuid,
    is_matched boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    hospital_id uuid,
    uhid character varying,
    settlement_date date
);


--
-- Name: claims_operations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.claims_operations AS
 SELECT h.id AS case_id,
    h.hospital_id,
    h.uhid,
    h.claim_number,
    h.current_stage,
    h.case_status,
    h.created_at,
    cl.status AS claim_status,
    cl.submitted_at,
    cl.processed_at,
    cl.claimed_amount,
    cl.approved_amount AS claim_approved_amount,
    prov.name AS provider_name,
    prov.tpa_name,
    hosp.name AS hospital_name,
    ct.avg_turnaround,
    ct.max_turnaround,
    ct.transition_count,
    COALESCE(st.settled_amount, (0)::numeric) AS settled_amount,
    COALESCE(st.disallowance, (0)::numeric) AS disallowance
   FROM (((((public.hospitalization h
     LEFT JOIN public.claims cl ON ((cl.hospitalization_id = h.id)))
     LEFT JOIN public.policy_provider_configs prov ON ((prov.id = h.policy_provider_id)))
     LEFT JOIN public.hospitals hosp ON ((hosp.id = h.hospital_id)))
     LEFT JOIN ( SELECT claim_status_tracking.hospitalization_id,
            avg(claim_status_tracking.turn_around_time) AS avg_turnaround,
            max(claim_status_tracking.turn_around_time) AS max_turnaround,
            count(*) AS transition_count
           FROM public.claim_status_tracking
          GROUP BY claim_status_tracking.hospitalization_id) ct ON ((ct.hospitalization_id = h.id)))
     LEFT JOIN ( SELECT settlement_item.hospitalization_id,
            sum(settlement_item.settled_amount) AS settled_amount,
            sum(settlement_item.disallowance) AS disallowance
           FROM public.settlement_item
          GROUP BY settlement_item.hospitalization_id) st ON ((st.hospitalization_id = h.id)));


--
-- Name: pre_auth; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pre_auth (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    hospitalization_id uuid,
    preauth_status character varying DEFAULT 'DRAFT'::character varying NOT NULL,
    preauth_raised_amount numeric(12,2),
    preauth_approved_amount numeric(12,2),
    hospital_id uuid
);


--
-- Name: form_data_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.form_data_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: form_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.form_data_id_seq OWNED BY public.pre_auth.id;


--
-- Name: hospital_provider_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hospital_provider_mappings (
    id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    policy_provider_id uuid NOT NULL,
    room_charges jsonb,
    extracted_data jsonb,
    mou_original_filename character varying,
    mou_stored_filename character varying,
    mou_file_path character varying,
    mou_content_type character varying,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


--
-- Name: patient_personal_detail; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.patient_personal_detail (
    id bigint NOT NULL,
    form_data_id bigint NOT NULL,
    patient_name text,
    gender text,
    address text,
    age_years integer,
    occupation text,
    employee_id text,
    date_of_birth date,
    policy_number text,
    contact_number text,
    corporate_name text,
    insured_card_id text,
    has_other_insurance boolean,
    has_family_physician boolean,
    family_physician_name text,
    family_physician_contact text,
    other_insurance_company text,
    other_insurance_details text,
    relative_contact_number text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    hospitalization_id uuid,
    uhid character varying
);


--
-- Name: pre_auth_patient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pre_auth_patient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pre_auth_patient_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pre_auth_patient_id_seq OWNED BY public.patient_personal_detail.id;


--
-- Name: preauth_status_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.preauth_status_tracking (
    id bigint NOT NULL,
    hospitalization_id uuid NOT NULL,
    uhid character varying,
    from_status character varying,
    to_status character varying NOT NULL,
    turn_around_time interval,
    document_link jsonb,
    remark text,
    created_at timestamp with time zone DEFAULT now(),
    turn_around_time_text character varying,
    email_id bigint,
    hospital_id uuid
);


--
-- Name: preauth_operations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.preauth_operations AS
 SELECT h.id AS case_id,
    h.hospital_id,
    h.uhid,
    h.claim_number,
    h.current_stage,
    h.case_status,
    h.preauth_outcome,
    h.created_at,
    pa.preauth_status,
    pa.preauth_raised_amount,
    pa.preauth_approved_amount,
    (pa.preauth_raised_amount - pa.preauth_approved_amount) AS preauth_shortfall_amount,
    prov.name AS provider_name,
    prov.tpa_name,
    hosp.name AS hospital_name,
    pt.avg_turnaround,
    pt.max_turnaround,
    pt.min_turnaround,
    pt.transition_count,
    pt.adr_count
   FROM ((((public.hospitalization h
     LEFT JOIN public.pre_auth pa ON ((pa.hospitalization_id = h.id)))
     LEFT JOIN public.policy_provider_configs prov ON ((prov.id = h.policy_provider_id)))
     LEFT JOIN public.hospitals hosp ON ((hosp.id = h.hospital_id)))
     LEFT JOIN ( SELECT preauth_status_tracking.hospitalization_id,
            avg(preauth_status_tracking.turn_around_time) AS avg_turnaround,
            max(preauth_status_tracking.turn_around_time) AS max_turnaround,
            min(preauth_status_tracking.turn_around_time) AS min_turnaround,
            count(*) AS transition_count,
            count(*) FILTER (WHERE ((preauth_status_tracking.to_status)::text = 'ADR_NMI'::text)) AS adr_count
           FROM public.preauth_status_tracking
          GROUP BY preauth_status_tracking.hospitalization_id) pt ON ((pt.hospitalization_id = h.id)));


--
-- Name: preauth_status_tracking_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.preauth_status_tracking_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: preauth_status_tracking_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.preauth_status_tracking_id_seq OWNED BY public.preauth_status_tracking.id;


--
-- Name: revenue_lifecycle; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.revenue_lifecycle AS
 SELECT h.id AS case_id,
    h.hospital_id,
    h.uhid,
    h.claim_number,
    h.current_stage,
    h.case_status,
    h.preauth_outcome,
    h.created_at,
    pd.patient_name,
    pd.gender,
    pd.age_years,
    pd.occupation,
    pd.corporate_name,
    pd.policy_number,
    pd.has_other_insurance,
    pa.preauth_status,
    pa.preauth_raised_amount,
    pa.preauth_approved_amount,
    cl.status AS claim_status,
    cl.claimed_amount,
    cl.approved_amount AS claim_approved_amount,
    prov.name AS provider_name,
    prov.tpa_name,
    hosp.name AS hospital_name,
    COALESCE(( SELECT sum(si.settled_amount) AS sum
           FROM public.settlement_item si
          WHERE (si.hospitalization_id = h.id)), (0)::numeric) AS settled_amount,
    COALESCE(( SELECT count(*) AS count
           FROM public.claim_case_emails em
          WHERE (em.claim_case_id = h.id)), (0)::bigint) AS email_count
   FROM (((((public.hospitalization h
     LEFT JOIN public.patient_personal_detail pd ON ((pd.hospitalization_id = h.id)))
     LEFT JOIN public.pre_auth pa ON ((pa.hospitalization_id = h.id)))
     LEFT JOIN public.claims cl ON ((cl.hospitalization_id = h.id)))
     LEFT JOIN public.policy_provider_configs prov ON ((prov.id = h.policy_provider_id)))
     LEFT JOIN public.hospitals hosp ON ((hosp.id = h.hospital_id)));


--
-- Name: settlement_batch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settlement_batch (
    id uuid NOT NULL,
    hospital_id uuid NOT NULL,
    tpa_insurer character varying,
    total_settlement_amount numeric(14,2),
    payment_mode character varying,
    payment_batch character varying,
    utr_number character varying,
    settlement_number character varying,
    settlement_date date,
    hospital_account_number character varying,
    source_original_filename character varying,
    source_stored_filename character varying,
    source_file_path character varying,
    source_content_type character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    policy_provider_id uuid
);


--
-- Name: settlement_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.settlement_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: settlement_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.settlement_item_id_seq OWNED BY public.settlement_item.id;


--
-- Name: claim_case_emails id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_case_emails ALTER COLUMN id SET DEFAULT nextval('public.claim_case_emails_id_seq'::regclass);


--
-- Name: claim_status_tracking id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_status_tracking ALTER COLUMN id SET DEFAULT nextval('public.claim_status_tracking_id_seq'::regclass);


--
-- Name: claims id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims ALTER COLUMN id SET DEFAULT nextval('public.claims_id_seq'::regclass);


--
-- Name: patient_personal_detail id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_personal_detail ALTER COLUMN id SET DEFAULT nextval('public.pre_auth_patient_id_seq'::regclass);


--
-- Name: pre_auth id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pre_auth ALTER COLUMN id SET DEFAULT nextval('public.form_data_id_seq'::regclass);


--
-- Name: preauth_status_tracking id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preauth_status_tracking ALTER COLUMN id SET DEFAULT nextval('public.preauth_status_tracking_id_seq'::regclass);


--
-- Name: settlement_item id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_item ALTER COLUMN id SET DEFAULT nextval('public.settlement_item_id_seq'::regclass);


--
-- Name: claim_case_emails claim_case_emails_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_case_emails
    ADD CONSTRAINT claim_case_emails_message_id_key UNIQUE (message_id);


--
-- Name: claim_case_emails claim_case_emails_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_case_emails
    ADD CONSTRAINT claim_case_emails_pkey PRIMARY KEY (id);


--
-- Name: hospitalization claim_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitalization
    ADD CONSTRAINT claim_cases_pkey PRIMARY KEY (id);


--
-- Name: hospitalization claim_cases_thread_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitalization
    ADD CONSTRAINT claim_cases_thread_id_key UNIQUE (thread_id);


--
-- Name: claim_status_tracking claim_status_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_status_tracking
    ADD CONSTRAINT claim_status_tracking_pkey PRIMARY KEY (id);


--
-- Name: claims claims_hospitalization_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_hospitalization_id_key UNIQUE (hospitalization_id);


--
-- Name: claims claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (id);


--
-- Name: pre_auth form_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pre_auth
    ADD CONSTRAINT form_data_pkey PRIMARY KEY (id);


--
-- Name: hospital_provider_mappings hospital_provider_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospital_provider_mappings
    ADD CONSTRAINT hospital_provider_mappings_pkey PRIMARY KEY (id);


--
-- Name: hospitals hospitals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitals
    ADD CONSTRAINT hospitals_pkey PRIMARY KEY (id);


--
-- Name: policy_provider_configs policy_provider_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_provider_configs
    ADD CONSTRAINT policy_provider_configs_pkey PRIMARY KEY (id);


--
-- Name: policy_provider_configs policy_provider_configs_provider_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_provider_configs
    ADD CONSTRAINT policy_provider_configs_provider_id_key UNIQUE (provider_id);


--
-- Name: patient_personal_detail pre_auth_patient_form_data_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_personal_detail
    ADD CONSTRAINT pre_auth_patient_form_data_id_key UNIQUE (form_data_id);


--
-- Name: patient_personal_detail pre_auth_patient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_personal_detail
    ADD CONSTRAINT pre_auth_patient_pkey PRIMARY KEY (id);


--
-- Name: preauth_status_tracking preauth_status_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preauth_status_tracking
    ADD CONSTRAINT preauth_status_tracking_pkey PRIMARY KEY (id);


--
-- Name: settlement_batch settlement_batch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_batch
    ADD CONSTRAINT settlement_batch_pkey PRIMARY KEY (id);


--
-- Name: settlement_item settlement_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_item
    ADD CONSTRAINT settlement_item_pkey PRIMARY KEY (id);


--
-- Name: hospital_provider_mappings uq_hospital_provider; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospital_provider_mappings
    ADD CONSTRAINT uq_hospital_provider UNIQUE (hospital_id, policy_provider_id);


--
-- Name: ix_claim_case_emails_claim_case_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_case_emails_claim_case_id ON public.claim_case_emails USING btree (claim_case_id);


--
-- Name: ix_claim_case_emails_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_case_emails_message_id ON public.claim_case_emails USING btree (message_id);


--
-- Name: ix_claim_cases_uhid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_cases_uhid ON public.hospitalization USING btree (uhid);


--
-- Name: ix_claim_status_tracking_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_status_tracking_hospital_id ON public.claim_status_tracking USING btree (hospital_id);


--
-- Name: ix_claim_status_tracking_hospitalization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claim_status_tracking_hospitalization_id ON public.claim_status_tracking USING btree (hospitalization_id);


--
-- Name: ix_claims_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_hospital_id ON public.claims USING btree (hospital_id);


--
-- Name: ix_claims_hospitalization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_claims_hospitalization_id ON public.claims USING btree (hospitalization_id);


--
-- Name: ix_patient_personal_detail_form_data_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_patient_personal_detail_form_data_id ON public.patient_personal_detail USING btree (form_data_id);


--
-- Name: ix_pre_auth_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pre_auth_hospital_id ON public.pre_auth USING btree (hospital_id);


--
-- Name: ix_preauth_status_tracking_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_preauth_status_tracking_hospital_id ON public.preauth_status_tracking USING btree (hospital_id);


--
-- Name: ix_preauth_status_tracking_hospitalization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_preauth_status_tracking_hospitalization_id ON public.preauth_status_tracking USING btree (hospitalization_id);


--
-- Name: ix_settlement_batch_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_batch_hospital_id ON public.settlement_batch USING btree (hospital_id);


--
-- Name: ix_settlement_batch_policy_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_batch_policy_provider_id ON public.settlement_batch USING btree (policy_provider_id);


--
-- Name: ix_settlement_item_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_item_batch_id ON public.settlement_item USING btree (batch_id);


--
-- Name: ix_settlement_item_claim_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_item_claim_number ON public.settlement_item USING btree (claim_number);


--
-- Name: ix_settlement_item_hospital_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_item_hospital_id ON public.settlement_item USING btree (hospital_id);


--
-- Name: ix_settlement_item_hospitalization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_settlement_item_hospitalization_id ON public.settlement_item USING btree (hospitalization_id);


--
-- Name: settlement_item trg_fill_settlement_item_denorm; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_fill_settlement_item_denorm BEFORE INSERT OR UPDATE OF batch_id, hospitalization_id ON public.settlement_item FOR EACH ROW EXECUTE FUNCTION public.fill_settlement_item_denorm();


--
-- Name: claim_case_emails claim_case_emails_claim_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_case_emails
    ADD CONSTRAINT claim_case_emails_claim_case_id_fkey FOREIGN KEY (claim_case_id) REFERENCES public.hospitalization(id);


--
-- Name: hospitalization claim_cases_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitalization
    ADD CONSTRAINT claim_cases_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: hospitalization claim_cases_policy_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospitalization
    ADD CONSTRAINT claim_cases_policy_provider_id_fkey FOREIGN KEY (policy_provider_id) REFERENCES public.policy_provider_configs(id);


--
-- Name: claim_status_tracking claim_status_tracking_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_status_tracking
    ADD CONSTRAINT claim_status_tracking_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.claim_case_emails(id);


--
-- Name: claim_status_tracking claim_status_tracking_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_status_tracking
    ADD CONSTRAINT claim_status_tracking_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: claim_status_tracking claim_status_tracking_hospitalization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_status_tracking
    ADD CONSTRAINT claim_status_tracking_hospitalization_id_fkey FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- Name: claims claims_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: claims claims_hospitalization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_hospitalization_id_fkey FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- Name: patient_personal_detail fk_patient_personal_detail_hospitalization; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_personal_detail
    ADD CONSTRAINT fk_patient_personal_detail_hospitalization FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- Name: preauth_status_tracking fk_preauth_status_tracking_email; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preauth_status_tracking
    ADD CONSTRAINT fk_preauth_status_tracking_email FOREIGN KEY (email_id) REFERENCES public.claim_case_emails(id);


--
-- Name: settlement_batch fk_settlement_batch_policy_provider_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_batch
    ADD CONSTRAINT fk_settlement_batch_policy_provider_id FOREIGN KEY (policy_provider_id) REFERENCES public.policy_provider_configs(id);


--
-- Name: hospital_provider_mappings hospital_provider_mappings_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospital_provider_mappings
    ADD CONSTRAINT hospital_provider_mappings_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: hospital_provider_mappings hospital_provider_mappings_policy_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hospital_provider_mappings
    ADD CONSTRAINT hospital_provider_mappings_policy_provider_id_fkey FOREIGN KEY (policy_provider_id) REFERENCES public.policy_provider_configs(id);


--
-- Name: pre_auth pre_auth_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pre_auth
    ADD CONSTRAINT pre_auth_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: pre_auth pre_auth_hospitalization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pre_auth
    ADD CONSTRAINT pre_auth_hospitalization_id_fkey FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- Name: patient_personal_detail pre_auth_patient_form_data_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_personal_detail
    ADD CONSTRAINT pre_auth_patient_form_data_id_fkey FOREIGN KEY (form_data_id) REFERENCES public.pre_auth(id) ON DELETE CASCADE;


--
-- Name: preauth_status_tracking preauth_status_tracking_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preauth_status_tracking
    ADD CONSTRAINT preauth_status_tracking_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: preauth_status_tracking preauth_status_tracking_hospitalization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preauth_status_tracking
    ADD CONSTRAINT preauth_status_tracking_hospitalization_id_fkey FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- Name: settlement_batch settlement_batch_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_batch
    ADD CONSTRAINT settlement_batch_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: settlement_item settlement_item_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_item
    ADD CONSTRAINT settlement_item_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.settlement_batch(id) ON DELETE CASCADE;


--
-- Name: settlement_item settlement_item_hospital_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_item
    ADD CONSTRAINT settlement_item_hospital_id_fkey FOREIGN KEY (hospital_id) REFERENCES public.hospitals(id);


--
-- Name: settlement_item settlement_item_hospitalization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settlement_item
    ADD CONSTRAINT settlement_item_hospitalization_id_fkey FOREIGN KEY (hospitalization_id) REFERENCES public.hospitalization(id);


--
-- PostgreSQL database dump complete
--

\unrestrict dUlmQaJkMSt2dGTXZS8umscbjUZz7FdNWKyagZbW3tnnmao9Z3wW7I8OyVdf3kZ

