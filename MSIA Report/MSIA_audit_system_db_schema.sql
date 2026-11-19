-- MSIA 审核管理系统数据库模式
-- 适用于 MySQL / PostgreSQL / SQL Server

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(150) NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL,
    department VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(100) NOT NULL UNIQUE,
    type VARCHAR(100),
    cmc_ame VARCHAR(150),
    plant_me VARCHAR(150),
    inalfa_kickoff DATE,
    supplier_kickoff DATE,
    design_freeze DATE,
    pvp VARCHAR(150),
    inalfa_sop VARCHAR(150),
    status VARCHAR(50) NOT NULL DEFAULT 'not_started',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE phases (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    timing_description TEXT,
    main_targets TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    score DECIMAL(5,2) DEFAULT 0,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, code)
);

CREATE TABLE check_items (
    id SERIAL PRIMARY KEY,
    phase_code VARCHAR(20) NOT NULL,
    item_no VARCHAR(20) NOT NULL,
    name VARCHAR(255) NOT NULL,
    request TEXT,
    is_key_item BOOLEAN NOT NULL DEFAULT FALSE,
    reviewer_roles VARCHAR(255),
    reference_documents TEXT,
    score_scale_type VARCHAR(50) NOT NULL,
    score_options TEXT,
    default_result_text TEXT,
    remarks TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(phase_code, item_no)
);

CREATE TABLE review_records (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES check_items(id) ON DELETE CASCADE,
    reviewer_id INTEGER REFERENCES users(id),
    score DECIMAL(5,2),
    comments TEXT,
    evidence_urls TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, phase_id, item_id, reviewer_id)
);

CREATE TABLE issues (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES check_items(id),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    owner_user_id INTEGER REFERENCES users(id),
    owner_department VARCHAR(100),
    priority VARCHAR(20) DEFAULT 'medium',
    due_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'Open',
    closing_status VARCHAR(100),
    remarks TEXT,
    evidence_urls TEXT,
    verification_comments TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE record_entries (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES check_items(id),
    msia_code VARCHAR(20),
    item_name VARCHAR(255),
    request TEXT,
    result TEXT,
    comments TEXT,
    issue_due_date DATE,
    issue_status VARCHAR(50),
    remarks TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT,
    type VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'Unread',
    link VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_phases_project ON phases(project_id);
CREATE INDEX idx_review_records_project ON review_records(project_id);
CREATE INDEX idx_issues_project ON issues(project_id);
CREATE INDEX idx_record_entries_project ON record_entries(project_id);
CREATE INDEX idx_notifications_user ON notifications(user_id);
