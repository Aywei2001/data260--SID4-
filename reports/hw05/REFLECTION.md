In the process of running this file, an offline test is executed. This will evaluate loop safeguards that are implemented for these tests. The MockModel class is utilized in this test to oversee everything.  The tests will look through the MCP tools search_grocery_recalls, recall_detail_lookup, and aggregate_company_stats.

The harness starts out by sending the test inputs to MockModel class, which then targets search_grocery_recalls.  Afterwards, the harness goes through execute_tool which starts a safety check of the input and ensures that nothing entered has any keywords that indicates it is a restricted or unauthorized record: all details are recorded.

After one test is done, the step count then increments, and the next test will be sent to MockModel. The harness will terminate execution if the max steps are exceeded.
