"""Declarative SQLite schema for fresh installations."""

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT,
  display_name TEXT NOT NULL,
  active_company_id INTEGER
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  owner_id INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
  company_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  joined_at TEXT NOT NULL,
  PRIMARY KEY (company_id, user_id),
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  author_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
  budget INTEGER NOT NULL CHECK(budget BETWEEN 1 AND 5),
  duration INTEGER NOT NULL CHECK(duration BETWEEN 1 AND 5),
  anonymous INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS voting_rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
  round_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  idea_id INTEGER NOT NULL,
  PRIMARY KEY (round_id, user_id),
  FOREIGN KEY (round_id) REFERENCES voting_rounds(id) ON DELETE CASCADE,
  FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  idea_id INTEGER NOT NULL,
  scheduled_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned',
  photo_file_id TEXT,
  reminder_day_sent INTEGER NOT NULL DEFAULT 0,
  reminder_event_sent INTEGER NOT NULL DEFAULT 0,
  reminder_followup_sent INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (idea_id) REFERENCES ideas(id)
);
CREATE TABLE IF NOT EXISTS activity_participants (
  activity_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  confirmed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (activity_id, user_id),
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS idea_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS idea_reactions (
  idea_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  emoji TEXT NOT NULL,
  PRIMARY KEY (idea_id,user_id,emoji),
  FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS date_options (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  scheduled_at TEXT NOT NULL,
  created_by INTEGER NOT NULL,
  FOREIGN KEY (round_id) REFERENCES voting_rounds(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS date_votes (
  option_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY (option_id,user_id),
  FOREIGN KEY (option_id) REFERENCES date_options(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS activity_photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL,
  uploaded_by INTEGER NOT NULL,
  storage_path TEXT,
  telegram_file_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY,
  reminder_week INTEGER NOT NULL DEFAULT 1,
  reminder_day INTEGER NOT NULL DEFAULT 1,
  reminder_hours INTEGER NOT NULL DEFAULT 1,
  reminder_event INTEGER NOT NULL DEFAULT 1,
  reminder_followup INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_idea_comments_idea_id ON idea_comments(idea_id);
CREATE INDEX IF NOT EXISTS idx_ideas_company_status ON ideas(company_id,status,id);
CREATE INDEX IF NOT EXISTS idx_members_user_id ON members(user_id);
CREATE INDEX IF NOT EXISTS idx_voting_rounds_company_status ON voting_rounds(company_id,status,id);
CREATE INDEX IF NOT EXISTS idx_votes_round_idea ON votes(round_id,idea_id);
CREATE INDEX IF NOT EXISTS idx_activities_company_status ON activities(company_id,status,scheduled_at);
CREATE INDEX IF NOT EXISTS idx_reactions_idea ON idea_reactions(idea_id);
CREATE INDEX IF NOT EXISTS idx_date_options_round_id ON date_options(round_id);
CREATE INDEX IF NOT EXISTS idx_activity_photos_activity_id ON activity_photos(activity_id);
"""
