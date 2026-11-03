(1) What you used an AI assistant for and what you did yourself:

All the initial code and logic was planned out and implemented on my own. AI was used after the implementation to detect and then correct and debug any issues that were currently occurring with the code

(2) One AI-produced output that was wrong/unsuitable, or one thing you independently verified

When running the planner, writer and reviewer agent files in part 2 I searched both the internet and asked ChatGPT about the process of starting up the agents and outputs to look for. Some of the corrections suggested by ChatGPT during debugging allowed the agents to successfully run without crashing, but did not allow me to successfully set up Kafka and in turn allow the agents to properly start up and communicate with one another.

(3) How you detected the problem or verified the result:

All three of the agents were supposed to send a "ready" message when properly started up, but instead the files only ran in the terminal for over a minute without any further messages being displayed. This was the first indication that something was wrong and there could be steps set up incorrectly or missing.

(4) What you changed and why it works now:

I eventually figured out that when starting up Docker, it was connecting to localhost instead of 127.0.0.1 where the agents were connecting. Changing this allowed the agents to function properly. This was a suggestion that I did not look over carefully.