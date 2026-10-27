# Threat model

| Attacker goal | Condition that would let it succeed |
|---|---|
| Override the recommendation | Retrieved pricing-page text is treated as trusted instructions and can change the agent's decision rules. |
| Make the SQL tool modify or expose data | The tool accepts model-generated SQL without enforcing a read-only SELECT boundary. |
| Put uploaded trip data in the final answer | The agent can return raw CSV rows or sensitive fields without filtering or output constraints. |