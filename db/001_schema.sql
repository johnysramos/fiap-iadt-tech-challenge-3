-- Assistente Clinico | schema completo
--
-- Tres schemas:
--   clinical   prontuarios sinteticos + a agenda de consultas
--   knowledge  protocolos internos do hospital, indexados para busca
--   audit      registro de tudo que o assistente fez

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS clinical;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS audit;


-- ===========================================================================
-- clinical
-- ===========================================================================
CREATE TABLE IF NOT EXISTS clinical.pacientes (
    id              text PRIMARY KEY,          -- P-0001
    nome            text NOT NULL,
    cpf             text NOT NULL,
    data_nascimento date NOT NULL,
    sexo            char(1) NOT NULL CHECK (sexo IN ('F', 'M')),
    convenio        text,
    criado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clinical.condicoes (
    id               serial PRIMARY KEY,
    paciente_id      text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    cid10            text NOT NULL,
    descricao        text NOT NULL,
    status           text NOT NULL CHECK (status IN ('ativa', 'resolvida')),
    diagnosticado_em date NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical.alergias (
    id            serial PRIMARY KEY,
    paciente_id   text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    substancia    text NOT NULL,
    classe        text,
    gravidade     text NOT NULL CHECK (gravidade IN ('leve', 'moderada', 'grave')),
    registrado_em date NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical.encontros (
    id                 text PRIMARY KEY,       -- E-000001
    paciente_id        text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    tipo               text NOT NULL CHECK (tipo IN ('emergencia', 'ambulatorial', 'internacao')),
    setor              text NOT NULL,
    inicio             timestamptz NOT NULL,
    fim                timestamptz,
    queixa_principal   text NOT NULL,
    medico_responsavel text NOT NULL,
    status             text NOT NULL CHECK (status IN ('aberto', 'encerrado'))
);

CREATE TABLE IF NOT EXISTS clinical.sinais_vitais (
    id          serial PRIMARY KEY,
    encontro_id text NOT NULL REFERENCES clinical.encontros(id) ON DELETE CASCADE,
    aferido_em  timestamptz NOT NULL,
    pas         int,             -- pressao sistolica (mmHg)
    pad         int,             -- pressao diastolica (mmHg)
    fc          int,             -- frequencia cardiaca (bpm)
    fr          int,             -- frequencia respiratoria (irpm)
    temperatura numeric(3, 1),
    spo2        int,
    dor         int CHECK (dor BETWEEN 0 AND 10)
);

CREATE TABLE IF NOT EXISTS clinical.exames (
    id            text PRIMARY KEY,            -- X-000001
    encontro_id   text NOT NULL REFERENCES clinical.encontros(id) ON DELETE CASCADE,
    paciente_id   text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    codigo        text NOT NULL,
    nome          text NOT NULL,
    categoria     text NOT NULL CHECK (categoria IN ('laboratorio', 'imagem', 'ecg')),
    urgencia      text NOT NULL CHECK (urgencia IN ('rotina', 'urgente')),
    solicitado_em timestamptz NOT NULL,
    status        text NOT NULL
                  CHECK (status IN ('solicitado', 'coletado', 'resultado_disponivel', 'cancelado'))
);

CREATE TABLE IF NOT EXISTS clinical.resultados_exame (
    id          serial PRIMARY KEY,
    exame_id    text NOT NULL REFERENCES clinical.exames(id) ON DELETE CASCADE,
    analito     text NOT NULL,
    valor       numeric,
    unidade     text,
    ref_min     numeric,
    ref_max     numeric,
    flag        text NOT NULL CHECK (flag IN ('normal', 'alterado', 'critico')),
    laudo       text,
    liberado_em timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical.prescricoes (
    id          text PRIMARY KEY,              -- R-000001
    encontro_id text NOT NULL REFERENCES clinical.encontros(id) ON DELETE CASCADE,
    paciente_id text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    medicamento text NOT NULL,
    classe      text NOT NULL,
    dose        text NOT NULL,
    via         text NOT NULL,
    frequencia  text NOT NULL,
    inicio      date NOT NULL,
    fim         date,
    status      text NOT NULL CHECK (status IN ('ativa', 'suspensa', 'encerrada')),
    prescritor  text NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical.notas_clinicas (
    id          serial PRIMARY KEY,
    encontro_id text NOT NULL REFERENCES clinical.encontros(id) ON DELETE CASCADE,
    paciente_id text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    tipo        text NOT NULL CHECK (tipo IN ('admissao', 'evolucao', 'alta')),
    autor       text NOT NULL,
    escrito_em  timestamptz NOT NULL,
    texto       text NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical.consultas (
    id            serial PRIMARY KEY,
    paciente_id   text NOT NULL REFERENCES clinical.pacientes(id) ON DELETE CASCADE,
    especialidade text NOT NULL,
    data_hora     timestamptz NOT NULL,
    motivo        text NOT NULL,
    confirmada    boolean NOT NULL DEFAULT false,
    agendada_por  text NOT NULL DEFAULT 'assistente',
    criada_em     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS encontros_paciente_idx        ON clinical.encontros (paciente_id, inicio DESC);
CREATE INDEX IF NOT EXISTS exames_paciente_idx           ON clinical.exames (paciente_id, solicitado_em DESC);
CREATE INDEX IF NOT EXISTS resultados_exame_idx          ON clinical.resultados_exame (exame_id);
CREATE INDEX IF NOT EXISTS prescricoes_paciente_idx      ON clinical.prescricoes (paciente_id, status);
CREATE INDEX IF NOT EXISTS alergias_paciente_idx         ON clinical.alergias (paciente_id);
CREATE INDEX IF NOT EXISTS condicoes_paciente_idx        ON clinical.condicoes (paciente_id, status);
CREATE INDEX IF NOT EXISTS notas_clinicas_paciente_idx   ON clinical.notas_clinicas (paciente_id, escrito_em DESC);
CREATE INDEX IF NOT EXISTS consultas_paciente_idx        ON clinical.consultas (paciente_id, data_hora);


-- ===========================================================================
-- knowledge
-- ===========================================================================
CREATE TABLE IF NOT EXISTS knowledge.protocolos (
    id            text PRIMARY KEY,            -- PROT-SCA-01
    titulo        text NOT NULL,
    especialidade text NOT NULL,
    resumo        text NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge.trechos (
    id           serial PRIMARY KEY,
    protocolo_id text NOT NULL REFERENCES knowledge.protocolos(id) ON DELETE CASCADE,
    ordem        int NOT NULL,
    secao        text NOT NULL,
    texto        text NOT NULL,
    embedding    vector(1536)                  -- preenchido por `python main.py setup`
);

CREATE INDEX IF NOT EXISTS trechos_embedding_idx ON knowledge.trechos
    USING hnsw (embedding vector_cosine_ops);


-- ===========================================================================
-- audit
-- ===========================================================================
CREATE TABLE IF NOT EXISTS audit.sessoes (
    id             uuid PRIMARY KEY,
    usuario        text NOT NULL,
    paciente_id    text,
    pergunta       text NOT NULL,
    resposta       text,
    status         text NOT NULL DEFAULT 'em_andamento'
                   CHECK (status IN ('em_andamento', 'concluida', 'bloqueada', 'erro')),
    tokens_entrada int NOT NULL DEFAULT 0,
    tokens_saida   int NOT NULL DEFAULT 0,
    iniciada_em    timestamptz NOT NULL DEFAULT now(),
    finalizada_em  timestamptz
);

CREATE TABLE IF NOT EXISTS audit.eventos (
    id          bigserial PRIMARY KEY,
    sessao_id   uuid NOT NULL REFERENCES audit.sessoes(id) ON DELETE CASCADE,
    ordem       int NOT NULL,
    tipo        text NOT NULL CHECK (tipo IN ('no', 'ferramenta', 'guardrail')),
    nome        text NOT NULL,
    detalhe     jsonb,
    latencia_ms int,
    ocorrido_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS eventos_sessao_idx ON audit.eventos (sessao_id, ordem);
CREATE INDEX IF NOT EXISTS sessoes_inicio_idx ON audit.sessoes (iniciada_em DESC);
