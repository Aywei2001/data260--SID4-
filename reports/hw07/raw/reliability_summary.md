# HW7 reliability results

Attempts: 20; model settings: `{"model_name": "llama3.2", "base_url": "http://localhost:11434", "temperature": 0.0}`

| Measure | Result |
|---|---:|
| Well-formed initial action | 7/20 (35.0%) |
| Well-formed after repair | 20/20 (100.0%) |
| Required chain complete | 19/20 (95.0%) |

| Failure type | Attempts affected |
|---|---:|
| malformed_arguments | 0 |
| unknown_tool | 0 |
| text_when_tool_required | 7 |
| lost_multi_step_chain | 19 |
| invalid_model_response | 6 |

Per-attempt data

| # | Task | Initial | Repaired | Chain | Failures |
|---:|---|---|---|---|---|
| 1 | reliability_A_1 | True | True | True | lost_multi_step_chain |
| 2 | reliability_B_2 | False | True | True | text_when_tool_required, text_when_tool_required |
| 3 | reliability_C_3 | False | True | True | text_when_tool_required, text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 4 | reliability_A_4 | True | True | True | lost_multi_step_chain |
| 5 | reliability_B_5 | False | True | True | invalid_model_response, lost_multi_step_chain |
| 6 | reliability_C_6 | False | True | True | text_when_tool_required, text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 7 | reliability_A_7 | True | True | True | lost_multi_step_chain |
| 8 | reliability_B_8 | False | True | True | invalid_model_response, lost_multi_step_chain |
| 9 | reliability_C_9 | False | True | False | text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 10 | reliability_A_10 | True | True | True | lost_multi_step_chain |
| 11 | reliability_B_11 | False | True | True | invalid_model_response, lost_multi_step_chain |
| 12 | reliability_C_12 | False | True | True | text_when_tool_required, text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 13 | reliability_A_13 | True | True | True | lost_multi_step_chain |
| 14 | reliability_B_14 | False | True | True | invalid_model_response, lost_multi_step_chain |
| 15 | reliability_C_15 | False | True | True | text_when_tool_required, text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 16 | reliability_A_16 | True | True | True | lost_multi_step_chain |
| 17 | reliability_B_17 | False | True | True | invalid_model_response, lost_multi_step_chain |
| 18 | reliability_C_18 | False | True | True | text_when_tool_required, text_when_tool_required, lost_multi_step_chain, lost_multi_step_chain |
| 19 | reliability_A_19 | True | True | True | lost_multi_step_chain |
| 20 | reliability_B_20 | False | True | True | invalid_model_response, lost_multi_step_chain |
