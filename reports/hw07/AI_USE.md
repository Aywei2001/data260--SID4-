(1) What you used an AI assistant for and what you did yourself:

All the initial code and logic was planned out and implemented on my own. AI was used after the implementation to detect and then correct and debug any issues that were currently occurring with the code

(2) One AI-produced output that was wrong/unsuitable, or one thing you independently verified

An AI-produced output that was wrong during the process of working on this assignment was during API testing in part 1. ChatGPT gave some suggestions such as Swagger which allowed me to test the APIs individually but did not allow me to generate 

(3) How you detected the problem or verified the result:

When I noticed that Swagger was only giving the output based on whether I successfully logged on to the reader1, writer1 and moderator1 accounts or not. It was not able to perform further actions such as generating the JWT token. A second prompt from ChatGPT suggested Postman. I did some additional research online about API testing tools that utilized JWT tokens and many sources confirmed it was to best one to use.

(4) What you changed and why it works now:

I was able to get the required results upon learning how to test the APIs using Postman.
