CREATE SCHEMA IF NOT EXISTS triad;
CREATE TABLE IF NOT EXISTS triad.improvement_slots (
 day date NOT NULL, agent text NOT NULL, work_item_id text NOT NULL,
 PRIMARY KEY(day,agent)
);
CREATE TABLE IF NOT EXISTS triad.cycle_slots (
 day date NOT NULL, mode text NOT NULL, cycle_id text NOT NULL, PRIMARY KEY(day,mode)
);
