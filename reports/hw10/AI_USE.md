(1) What you used an AI assistant for and what you did yourself:

All the initial code and logic was planned out and implemented on my own. AI was used after the implementation to detect and then correct and debug any issues that were currently occurring with the code

(2) One AI-produced output that was wrong/unsuitable, or one thing you independently verified
I used ChatGPT as guidance to help walk me through some sections that I found confusing as well as to debug files as a final check before running the. In one instance of the debugging process, there were lines of code that ChatGPT missed initially. Thank missing line was the reason that the file did not run properly even though ChatGPT stated that there were no errors. This was when I was working on hw10_evaluate_case.py

(3) How you detected the problem or verified the result:

When I looked through the code for a second time, I realized it was missing the line “from hw10_trace import init_trace_db, trace_stage” at the beginning of the file, which Chat missed.

(4) What you changed and why it works now:

The file was working properly after I added that line.
