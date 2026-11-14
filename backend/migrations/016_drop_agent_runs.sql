-- The separate agent-run API (and its tables) was removed. Service-request analysis is stored in service_analysis.
DROP TABLE IF EXISTS agent_run_asset;
DROP TABLE IF EXISTS agent_run;
