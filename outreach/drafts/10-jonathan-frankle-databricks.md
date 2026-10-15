To: jfrankle@databricks.com (work, published on jfrankle.com)
Subject: RLVR over joined public records
Status: DRAFT, not sent

Jonathan,

Your text-to-SQL paper notes that "the reward function is verifiable" in database tasks, the RLVR setting. This is that setting, but with spatial joins across seven public-record tables.

Public Records Gym is a tool-use environment over seven joined Minnesota record layers: parcels, sales, permits, inspections, cleanup sites. Answers are computed by SQL and graded without a model. A test split is held back. No GROUP BY in the tools. The agent does the aggregation itself.

Research use is free. Commercial training or evaluation needs a paid licence. Reply and I'll send the train split, the MCP harness and a baseline trace.

Best,
Aidan
MS, AI and ML, Columbia · randomaidan.substack.com
