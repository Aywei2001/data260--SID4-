Part 6 Metric run results:

| Metric | Result | What it means |
|---|---:|---|
| Precision (notify) | 100% | Every golden-set case labeled notify was expected to trigger an alert. |
| Recall (notify) | 100% | Every golden-set case expected to trigger an alert received notify. |
| Unnecessary notification rate | 0% | The evaluation found no false-positive notifications. |
| Duplicate notification rate | 0% | The recorded trace showed no repeated notification effects. The repost and retry were suppressed. |
| Restart recovery rate | 100% | All interrupted runs counted by the tool reached a recovered state. |
| Tokens per accepted alert | Unavailable | Muse showed 1% of the weekly Free plan allowance used without a token count, command was run without usage-tokens. |
