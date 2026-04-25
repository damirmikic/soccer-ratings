CREATE TABLE IF NOT EXISTS countries (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    country_path TEXT UNIQUE,
    latest_rating DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leagues (
    id BIGSERIAL PRIMARY KEY,
    country_id BIGINT REFERENCES countries(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    league_path TEXT NOT NULL UNIQUE,
    latest_rating DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    team_path TEXT UNIQUE,
    country_id BIGINT REFERENCES countries(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, team_path)
);

CREATE TABLE IF NOT EXISTS rating_snapshots (
    id BIGSERIAL PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('country', 'league', 'team')),
    mode TEXT NOT NULL DEFAULT 'general' CHECK (mode IN ('general', 'home', 'away')),
    country_id BIGINT REFERENCES countries(id) ON DELETE CASCADE,
    league_id BIGINT REFERENCES leagues(id) ON DELETE CASCADE,
    team_id BIGINT REFERENCES teams(id) ON DELETE CASCADE,
    ranking INTEGER,
    rating DOUBLE PRECISION NOT NULL,
    source_url TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS matches (
    id BIGSERIAL PRIMARY KEY,
    match_date DATE NOT NULL,
    competition TEXT NOT NULL,
    home_team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    away_team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    home_odds DOUBLE PRECISION NOT NULL,
    draw_odds DOUBLE PRECISION NOT NULL,
    away_odds DOUBLE PRECISION NOT NULL,
    home_rating DOUBLE PRECISION NOT NULL,
    away_rating DOUBLE PRECISION NOT NULL,
    home_goals INTEGER,
    away_goals INTEGER,
    result_text TEXT,
    source_team_id BIGINT REFERENCES teams(id) ON DELETE SET NULL,
    source_team_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (match_date, competition, home_team_id, away_team_id)
);

CREATE TABLE IF NOT EXISTS league_history_builds (
    id BIGSERIAL PRIMARY KEY,
    league_id BIGINT NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    raw_match_count INTEGER NOT NULL,
    deduped_match_count INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    built_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leagues_country_id ON leagues(country_id);
CREATE INDEX IF NOT EXISTS idx_teams_country_id ON teams(country_id);
CREATE INDEX IF NOT EXISTS idx_rating_snapshots_scope_mode ON rating_snapshots(scope, mode);
CREATE INDEX IF NOT EXISTS idx_matches_home_team_id ON matches(home_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_away_team_id ON matches(away_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_match_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_league_history_builds_league_id ON league_history_builds(league_id);
