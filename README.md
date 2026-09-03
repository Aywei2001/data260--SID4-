Why is prior conversation context resent with every turn? 
The conversation context needs to be resent  for every turn because the LLM will not remember the prompt after each turn and will need to have it resent so it can give another output.

How is a system prompt different from a user message?
A system prompt focuses on how an LLM will behave overall in a conversation. A user message is a single prompt request in which the LLM will answer in a conversation.

Why do input tokens grow over a conversation?
Input tokens grow over the course of a conversation due to the number of inputs during each turn of a conversation increasing. More are being sent at once.

What eventually limits that growth?
The LLM hitting a technological limit such as a window cap or memory constraints in the computer hardware.
