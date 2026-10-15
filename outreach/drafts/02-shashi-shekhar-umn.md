To: shekhar@cs.umn.edu (work, from the paper)
Subject: Autonomous GIS, graded against county records
Status: DRAFT, not sent

Professor Shekhar,

Your autonomous-GIS paper says the LLM can "independently generate and execute geoprocessing workflows." So I built a way to check it, on Twin Cities records.

Public Records Gym is a tool-use environment over seven joined Minnesota record layers: parcels, sales, permits, inspections, cleanup sites. Answers are computed by SQL and graded without a model. A test split is held back. The agent geocodes, buffers, filters by date and aggregates. Every step is a tool call. No model sits in the grading loop.

Research use is free. Commercial training or evaluation needs a paid licence. Reply and I'll send the train split, the MCP harness and a baseline trace.

Best,
Aidan
MS, AI and ML, Columbia · randomaidan.substack.com
